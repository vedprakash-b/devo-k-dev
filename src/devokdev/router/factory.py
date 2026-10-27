"""Building a ready-to-use router from settings.

``open_router`` owns the lifetimes: one shared HTTP client (connection pooling across all
calls) and one Redis connection, both closed when the block exits. If Redis is not
reachable, the router still works with in-memory state, and says so: quotas are then only
tracked inside this process, which is fine for a single CLI command and wrong for a fleet
of workers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from devokdev.config import Settings
from devokdev.llm.adapter import OpenAICompatAdapter, StreamTimeouts
from devokdev.llm.registry import Registry
from devokdev.router.gateway import Clock, Gateway
from devokdev.router.router import Router, RouterConfig, Sleep
from devokdev.router.state import BreakerConfig, MemoryRouterState, RouterState


@dataclass(frozen=True, slots=True)
class RouterContext:
    router: Router
    gateway: Gateway
    state_backend: str  # "redis" or "memory (Redis not reachable: ...)"


def stream_timeouts(settings: Settings) -> StreamTimeouts:
    return StreamTimeouts(
        first_token_s=settings.router_first_token_timeout_s,
        stall_s=settings.router_stall_timeout_s,
        total_s=settings.router_total_timeout_s,
    )


def breaker_config(settings: Settings) -> BreakerConfig:
    return BreakerConfig(
        failures_to_open=settings.router_breaker_failures,
        cooldown_s=settings.router_breaker_cooldown_s,
    )


@asynccontextmanager
async def _redis_or_memory(
    settings: Settings, use_redis: bool
) -> AsyncIterator[tuple[RouterState, str]]:
    config = breaker_config(settings)
    if not use_redis:
        yield MemoryRouterState(breaker_config=config), "memory"
        return
    from redis.asyncio import Redis

    from devokdev.router.redis_state import RedisRouterState

    client = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=5)
    try:
        await asyncio.wait_for(client.ping(), timeout=3)
    except Exception as exc:  # any connection problem: degrade, don't crash
        await client.aclose()
        reason = type(exc).__name__
        yield MemoryRouterState(breaker_config=config), f"memory (Redis not reachable: {reason})"
        return
    try:
        yield RedisRouterState(client, config), "redis"
    finally:
        await client.aclose()


@asynccontextmanager
async def open_router(
    settings: Settings,
    *,
    registry: Registry | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    use_redis: bool = True,
    clock: Clock = time.time,
    sleep: Sleep = asyncio.sleep,
) -> AsyncIterator[RouterContext]:
    """A router with its HTTP client and state, closed cleanly on exit."""
    registry = registry or Registry.load(settings.models_file)
    async with (
        httpx.AsyncClient(transport=transport) as client,
        _redis_or_memory(settings, use_redis) as (state, backend),
    ):
        adapter = OpenAICompatAdapter(client, stream_timeouts(settings), wall_clock=clock)
        gateway = Gateway(registry, settings, state, adapter, clock)
        config = RouterConfig(
            max_attempts=settings.router_max_attempts,
            switch_back_after_s=settings.router_switch_back_after_s,
        )
        yield RouterContext(Router(gateway, config, sleep=sleep), gateway, backend)

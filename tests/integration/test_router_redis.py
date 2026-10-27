"""Two routers, one Redis: a 429 seen by one worker benches the model for the other.

Run: make up && make test-integration
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from redis.asyncio import Redis

from devokdev.config import Settings
from devokdev.llm.adapter import OpenAICompatAdapter
from devokdev.llm.messages import CompletionRequest, Message
from devokdev.llm.scripted import Reply, ScriptedTransport
from devokdev.router.gateway import Gateway
from devokdev.router.redis_state import RedisRouterState
from devokdev.router.router import Router
from tests.support import FakeClock, make_registry, make_settings

pytestmark = pytest.mark.integration


async def test_a_bench_set_by_one_worker_is_respected_by_another() -> None:
    client = Redis.from_url(Settings().redis_url)
    prefix = f"devokdev:test:{uuid.uuid4().hex[:8]}:"
    clock = FakeClock()
    registry = make_registry()
    settings = make_settings()
    request = CompletionRequest(messages=(Message.user("hi"),))

    def worker(transport: ScriptedTransport) -> Router:
        state = RedisRouterState(client, prefix=prefix)
        adapter = OpenAICompatAdapter(httpx.AsyncClient(transport=transport), wall_clock=clock)
        return Router(Gateway(registry, settings, state, adapter, clock), sleep=clock.sleep)

    first = ScriptedTransport(
        {"alpha-large": [Reply.rate_limited(60)], "beta-coder": [Reply(text="b")]}
    )
    second = ScriptedTransport({"alpha-large": [Reply(text="a")], "beta-coder": [Reply(text="b")]})
    try:
        one = await worker(first).session("backend").complete(request)
        two = await worker(second).session("backend").complete(request)
    finally:
        keys = [key async for key in client.scan_iter(f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()

    assert one.model_id == "beta/beta-coder"
    # Worker two never even tried alpha: the bench lives in Redis.
    assert two.model_id == "beta/beta-coder"
    assert second.calls_to("alpha-large") == 0

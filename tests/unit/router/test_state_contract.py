"""One contract, two implementations.

Every test here runs against MemoryRouterState and, with --run-integration, against
RedisRouterState on the local stack. If the Lua scripts ever drift from the Python
version, the Redis run fails.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest

from devokdev.config import Settings
from devokdev.llm.ratelimits import Dimension, Window, WindowObservation
from devokdev.router.state import (
    UNKNOWN,
    BreakerConfig,
    BreakerState,
    Denied,
    MemoryRouterState,
    Reservation,
    RouterState,
    WindowLimit,
)

NOW = 1_800_000_000.0
MODEL = "alpha/alpha-large"
RPM = WindowLimit(f"model:{MODEL}", Dimension.REQUESTS, Window.MINUTE, 2)
TPM = WindowLimit(f"model:{MODEL}", Dimension.TOKENS, Window.MINUTE, 1000)
SHARED_RPD = WindowLimit("provider:alpha", Dimension.REQUESTS, Window.DAY, 3)
CONFIG = BreakerConfig(failures_to_open=3, cooldown_s=60, max_cooldown_s=900, trial_timeout_s=30)


@pytest.fixture(
    params=["memory", pytest.param("redis", marks=pytest.mark.integration)],
)
async def state(request: pytest.FixtureRequest) -> AsyncIterator[RouterState]:
    if request.param == "memory":
        yield MemoryRouterState(breaker_config=CONFIG)
        return
    from redis.asyncio import Redis

    from devokdev.router.redis_state import RedisRouterState

    client = Redis.from_url(Settings().redis_url)
    prefix = f"devokdev:test:{uuid.uuid4().hex[:8]}:"
    try:
        yield RedisRouterState(client, CONFIG, prefix=prefix)
    finally:
        keys = [key async for key in client.scan_iter(f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def reserve(state: RouterState, tokens: int = 100, now: float = NOW) -> Reservation | Denied:
    return await state.try_reserve(MODEL, [RPM, TPM, SHARED_RPD], 1, tokens, now)


async def test_reservations_spend_every_window_until_one_runs_out(state: RouterState) -> None:
    assert isinstance(await reserve(state), Reservation)
    assert isinstance(await reserve(state), Reservation)
    denied = await reserve(state)
    assert isinstance(denied, Denied)
    assert denied.window == RPM
    assert denied.retry_at == pytest.approx(NOW + 60)
    assert not denied.never_fits


async def test_a_window_refills_after_it_resets(state: RouterState) -> None:
    await reserve(state)
    await reserve(state)
    assert isinstance(await reserve(state, now=NOW + 61), Reservation)


async def test_shared_provider_windows_block_after_their_own_limit(state: RouterState) -> None:
    for minute in range(3):
        assert isinstance(await reserve(state, now=NOW + 61 * minute), Reservation)
    denied = await reserve(state, now=NOW + 61 * 3)
    assert isinstance(denied, Denied)
    assert denied.window == SHARED_RPD


async def test_a_denied_reservation_takes_nothing(state: RouterState) -> None:
    assert isinstance(await reserve(state, tokens=900), Reservation)
    assert isinstance(await reserve(state, tokens=200), Denied)  # 100 tokens left
    states = await state.window_states([RPM, TPM], NOW)
    assert states[RPM.key].remaining == 1  # the denied call took no request
    assert states[TPM.key].remaining == 100


async def test_a_call_bigger_than_the_whole_limit_never_fits(state: RouterState) -> None:
    denied = await reserve(state, tokens=5000)
    assert isinstance(denied, Denied)
    assert denied.never_fits


async def test_settling_corrects_the_token_estimate(state: RouterState) -> None:
    reservation = await reserve(state, tokens=300)
    assert isinstance(reservation, Reservation)
    await state.settle(reservation, actual_tokens=500)
    states = await state.window_states([TPM], NOW)
    assert states[TPM.key].remaining == 500


async def test_settling_after_the_window_rolled_over_changes_nothing(state: RouterState) -> None:
    reservation = await reserve(state, tokens=300)
    assert isinstance(reservation, Reservation)
    await reserve(state, tokens=10, now=NOW + 61)  # new window
    await state.settle(reservation, actual_tokens=900)
    states = await state.window_states([TPM], NOW + 61)
    assert states[TPM.key].remaining == 990


async def test_headers_overwrite_our_counts(state: RouterState) -> None:
    await reserve(state)
    obs = WindowObservation(
        Dimension.REQUESTS, Window.MINUTE, limit=30, remaining=0, reset_after_s=12
    )
    await state.observe([(RPM, obs)], NOW)
    denied = await reserve(state)
    assert isinstance(denied, Denied)
    assert denied.retry_at == pytest.approx(NOW + 12)
    states = await state.window_states([RPM], NOW + 13)
    assert states[RPM.key].limit == 30  # the learned limit outlives the window


async def test_unknown_limits_do_not_block(state: RouterState) -> None:
    unknown = WindowLimit("model:x", Dimension.REQUESTS, Window.DAY, UNKNOWN)
    for _ in range(5):
        assert isinstance(await state.try_reserve("x", [unknown], 1, 10, NOW), Reservation)


async def test_concurrent_reservations_never_overspend(state: RouterState) -> None:
    results = await asyncio.gather(*(reserve(state) for _ in range(10)))
    assert sum(isinstance(r, Reservation) for r in results) == 2


async def test_cooldowns_only_ever_extend(state: RouterState) -> None:
    await state.cool_down(MODEL, NOW + 30, "rate_limited")
    await state.cool_down(MODEL, NOW + 10, "rate_limited")
    health = (await state.health([MODEL]))[MODEL]
    assert health.cooldown_until == pytest.approx(NOW + 30)
    assert health.cooldown_reason == "rate_limited"
    assert health.benched_until(NOW) == pytest.approx(NOW + 30)
    assert health.benched_until(NOW + 31) is None


async def test_breaker_opens_after_repeated_failures(state: RouterState) -> None:
    assert await state.record_failure(MODEL, NOW) is BreakerState.CLOSED
    assert await state.record_failure(MODEL, NOW) is BreakerState.CLOSED
    assert await state.record_failure(MODEL, NOW) is BreakerState.OPEN
    assert not await state.allow_attempt(MODEL, NOW + 59)
    health = (await state.health([MODEL]))[MODEL]
    assert health.breaker is BreakerState.OPEN
    assert health.benched_until(NOW) == pytest.approx(NOW + 60)


async def test_half_open_allows_exactly_one_trial(state: RouterState) -> None:
    for _ in range(3):
        await state.record_failure(MODEL, NOW)
    assert await state.allow_attempt(MODEL, NOW + 60)  # the trial
    assert not await state.allow_attempt(MODEL, NOW + 61)  # trial still in flight
    assert await state.allow_attempt(MODEL, NOW + 91)  # trial timed out: another one


async def test_a_successful_trial_closes_the_breaker(state: RouterState) -> None:
    for _ in range(3):
        await state.record_failure(MODEL, NOW)
    await state.allow_attempt(MODEL, NOW + 60)
    await state.record_success(MODEL)
    assert (await state.health([MODEL]))[MODEL].breaker is BreakerState.CLOSED
    assert await state.allow_attempt(MODEL, NOW + 61)


async def test_a_failed_trial_reopens_with_a_doubled_cooldown(state: RouterState) -> None:
    for _ in range(3):
        await state.record_failure(MODEL, NOW)
    await state.allow_attempt(MODEL, NOW + 60)
    assert await state.record_failure(MODEL, NOW + 60) is BreakerState.OPEN
    health = (await state.health([MODEL]))[MODEL]
    assert health.open_until == pytest.approx(NOW + 60 + 120)

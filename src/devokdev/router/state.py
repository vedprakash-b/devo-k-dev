"""Router state: quota windows, cooldowns and circuit breakers.

Three kinds of state decide whether a model may be called right now:

- **Quota windows.** One per (scope, dimension, window), for example
  ``model:groq/openai/gpt-oss-120b | tokens | minute``. A window holds a limit, what is
  left, and when it resets. A call *reserves* its estimated cost in every window that
  applies before it is made, atomically, so two agents cannot both take the last request.
  After the call, the reservation is *settled* with the real token count, and the
  provider's rate-limit headers *overwrite* our counts, because the provider is the
  source of truth. Scope ``provider:openrouter`` covers quotas a provider shares across
  models.
- **Cooldowns.** After a 429 or a used-up daily quota, a model is benched until a time.
- **Circuit breakers.** Repeated server or network failures *open* a model's breaker for
  a cooldown that doubles each time it trips. After the cooldown it goes *half-open* and
  lets exactly one trial call through: success closes it, failure opens it again.

The same contract has two implementations. ``MemoryRouterState`` (here) serves tests and
single-process use; ``RedisRouterState`` (``redis_state.py``) is shared by every worker.
One contract test suite runs against both.

Times are passed in as epoch seconds and stored as integer milliseconds, so both
implementations do exactly the same arithmetic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Protocol

from devokdev.llm.ratelimits import WINDOW_SECONDS, Dimension, Window, WindowObservation

UNKNOWN = -1  # an unknown limit or remaining count


def to_ms(seconds: float) -> int:
    return round(seconds * 1000)


@dataclass(frozen=True, slots=True)
class WindowLimit:
    """One quota window that applies to a call, with its configured limit (or UNKNOWN)."""

    scope: str
    dimension: Dimension
    window: Window
    limit: int = UNKNOWN

    @property
    def key(self) -> str:
        return f"{self.scope}|{self.dimension.value}|{self.window.value}"

    @property
    def period_ms(self) -> int:
        return to_ms(WINDOW_SECONDS[self.window])


@dataclass(frozen=True, slots=True)
class WindowState:
    limit: int
    remaining: int
    resets_at_ms: int

    @property
    def fraction_left(self) -> float | None:
        if self.limit <= 0 or self.remaining < 0:
            return None
        return min(1.0, self.remaining / self.limit)


@dataclass(frozen=True, slots=True)
class Reservation:
    """Quota taken for one call; settle it once the real usage is known."""

    model_id: str
    windows: tuple[WindowLimit, ...]
    tokens: int
    marks: tuple[int, ...]  # each window's reset time when reserved


@dataclass(frozen=True, slots=True)
class Denied:
    """No quota left. ``retry_at`` is when the blocking window resets."""

    window: WindowLimit
    retry_at: float
    never_fits: bool = False  # the call is larger than the window's whole limit


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class ModelHealth:
    cooldown_until: float = 0.0
    cooldown_reason: str = ""
    breaker: BreakerState = BreakerState.CLOSED
    failures: int = 0
    open_until: float = 0.0

    def benched_until(self, now: float) -> float | None:
        """When this model can be used again, or None if it can be used now."""
        times = [self.cooldown_until] if self.cooldown_until > now else []
        if self.breaker is BreakerState.OPEN and self.open_until > now:
            times.append(self.open_until)
        return max(times) if times else None


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    failures_to_open: int = 3
    cooldown_s: float = 60.0
    max_cooldown_s: float = 900.0
    trial_timeout_s: float = 120.0  # how long a half-open trial may take before another


def cost_of(window: WindowLimit, requests: int, tokens: int) -> int:
    return requests if window.dimension is Dimension.REQUESTS else tokens


def breaker_cooldown_ms(config: BreakerConfig, trips: int) -> int:
    seconds = min(config.cooldown_s * (2 ** max(0, trips - 1)), config.max_cooldown_s)
    return to_ms(seconds)


class RouterState(Protocol):
    async def try_reserve(
        self,
        model_id: str,
        windows: Sequence[WindowLimit],
        requests: int,
        tokens: int,
        now: float,
    ) -> Reservation | Denied: ...

    async def settle(self, reservation: Reservation, actual_tokens: int) -> None: ...

    async def observe(
        self, updates: Sequence[tuple[WindowLimit, WindowObservation]], now: float
    ) -> None: ...

    async def window_states(
        self, windows: Sequence[WindowLimit], now: float
    ) -> dict[str, WindowState]: ...

    async def cool_down(self, model_id: str, until: float, reason: str) -> None: ...

    async def health(self, model_ids: Sequence[str]) -> dict[str, ModelHealth]: ...

    async def allow_attempt(self, model_id: str, now: float) -> bool: ...

    async def record_success(self, model_id: str) -> None: ...

    async def record_failure(self, model_id: str, now: float) -> BreakerState: ...


# ------------------------------------------------------------------ in-memory implementation


@dataclass
class _Window:
    limit: int
    remaining: int
    resets_at_ms: int


@dataclass
class _Breaker:
    state: BreakerState = BreakerState.CLOSED
    failures: int = 0
    trips: int = 0
    open_until_ms: int = 0
    trial_until_ms: int = 0


@dataclass
class MemoryRouterState:
    """RouterState for one process. Same semantics as the Redis version, line for line."""

    breaker_config: BreakerConfig = field(default_factory=BreakerConfig)
    _windows: dict[str, _Window] = field(default_factory=dict)
    _cooldowns: dict[str, tuple[int, str]] = field(default_factory=dict)
    _breakers: dict[str, _Breaker] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _current(self, w: WindowLimit, now_ms: int) -> _Window:
        """The window as it stands now: rolled over if its reset time has passed.

        A limit learned from headers outlives the window it was learned in.
        """
        state = self._windows.get(w.key)
        if state is None or now_ms >= state.resets_at_ms:
            limit = state.limit if state is not None and state.limit >= 0 else w.limit
            return _Window(limit=limit, remaining=limit, resets_at_ms=now_ms + w.period_ms)
        if state.limit < 0 and w.limit >= 0:
            return replace(state, limit=w.limit)
        return state

    async def try_reserve(
        self,
        model_id: str,
        windows: Sequence[WindowLimit],
        requests: int,
        tokens: int,
        now: float,
    ) -> Reservation | Denied:
        now_ms = to_ms(now)
        async with self._lock:
            current = [self._current(w, now_ms) for w in windows]
            for w, state in zip(windows, current, strict=True):
                cost = cost_of(w, requests, tokens)
                if state.limit >= 0 and cost > state.limit:
                    return Denied(w, state.resets_at_ms / 1000, never_fits=True)
                if state.remaining >= 0 and cost > state.remaining:
                    return Denied(w, state.resets_at_ms / 1000)
            for w, state in zip(windows, current, strict=True):
                remaining = state.remaining
                if remaining >= 0:
                    remaining -= cost_of(w, requests, tokens)
                self._windows[w.key] = _Window(state.limit, remaining, state.resets_at_ms)
            return Reservation(
                model_id, tuple(windows), tokens, tuple(s.resets_at_ms for s in current)
            )

    async def settle(self, reservation: Reservation, actual_tokens: int) -> None:
        delta = actual_tokens - reservation.tokens
        async with self._lock:
            for w, mark in zip(reservation.windows, reservation.marks, strict=True):
                if w.dimension is not Dimension.TOKENS:
                    continue
                state = self._windows.get(w.key)
                if state is None or state.remaining < 0 or state.resets_at_ms != mark:
                    continue  # the window rolled over or headers replaced our count
                state.remaining = max(0, state.remaining - delta)

    async def observe(
        self, updates: Sequence[tuple[WindowLimit, WindowObservation]], now: float
    ) -> None:
        now_ms = to_ms(now)
        async with self._lock:
            for w, obs in updates:
                old = self._windows.get(w.key)
                limit = obs.limit if obs.limit is not None else (old.limit if old else w.limit)
                if obs.remaining is not None:
                    remaining = obs.remaining
                else:
                    remaining = old.remaining if old else limit
                if obs.reset_after_s is not None:
                    resets = now_ms + to_ms(obs.reset_after_s)
                else:
                    resets = old.resets_at_ms if old else now_ms + w.period_ms
                self._windows[w.key] = _Window(limit, remaining, resets)

    async def window_states(
        self, windows: Sequence[WindowLimit], now: float
    ) -> dict[str, WindowState]:
        now_ms = to_ms(now)
        async with self._lock:
            out: dict[str, WindowState] = {}
            for w in windows:
                s = self._current(w, now_ms)
                out[w.key] = WindowState(s.limit, s.remaining, s.resets_at_ms)
            return out

    async def cool_down(self, model_id: str, until: float, reason: str) -> None:
        until_ms = to_ms(until)
        async with self._lock:
            existing = self._cooldowns.get(model_id)
            if existing is None or until_ms > existing[0]:
                self._cooldowns[model_id] = (until_ms, reason)

    async def health(self, model_ids: Sequence[str]) -> dict[str, ModelHealth]:
        async with self._lock:
            out: dict[str, ModelHealth] = {}
            for model_id in model_ids:
                until_ms, reason = self._cooldowns.get(model_id, (0, ""))
                b = self._breakers.get(model_id, _Breaker())
                out[model_id] = ModelHealth(
                    cooldown_until=until_ms / 1000,
                    cooldown_reason=reason,
                    breaker=b.state,
                    failures=b.failures,
                    open_until=b.open_until_ms / 1000,
                )
            return out

    async def allow_attempt(self, model_id: str, now: float) -> bool:
        now_ms = to_ms(now)
        trial_ms = to_ms(self.breaker_config.trial_timeout_s)
        async with self._lock:
            b = self._breakers.get(model_id)
            if b is None or b.state is BreakerState.CLOSED:
                return True
            if b.state is BreakerState.OPEN:
                if now_ms < b.open_until_ms:
                    return False
                b.state = BreakerState.HALF_OPEN
                b.trial_until_ms = now_ms + trial_ms
                return True
            if now_ms < b.trial_until_ms:
                return False  # a trial call is already in flight
            b.trial_until_ms = now_ms + trial_ms
            return True

    async def record_success(self, model_id: str) -> None:
        async with self._lock:
            self._breakers.pop(model_id, None)

    async def record_failure(self, model_id: str, now: float) -> BreakerState:
        now_ms = to_ms(now)
        async with self._lock:
            b = self._breakers.setdefault(model_id, _Breaker())
            if (
                b.state is BreakerState.HALF_OPEN
                or b.failures + 1 >= self.breaker_config.failures_to_open
            ):
                b.trips += 1
                b.state = BreakerState.OPEN
                b.failures = 0
                b.open_until_ms = now_ms + breaker_cooldown_ms(self.breaker_config, b.trips)
            else:
                b.failures += 1
            return b.state

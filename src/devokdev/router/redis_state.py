"""RouterState in Redis, shared by every worker process.

Each operation that reads and then writes is one Lua script. Redis runs a script without
interleaving any other command, so "check every window, then take quota from all of them"
is atomic: two workers can never both spend the last request of a minute. The scripts
mirror ``MemoryRouterState`` line for line, and the same contract tests run on both.

Keys (all under a prefix, ``devokdev:router:`` by default):

- ``w:<scope>|<dimension>|<window>``: hash of limit, remaining, resets_at (ms)
- ``cd:<model>``: hash of until (ms), reason
- ``br:<model>``: hash of state, failures, trips, open_until, trial_until (ms)

Every key expires on its own once it can no longer matter, so Redis never fills up.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis

from devokdev.llm.ratelimits import WindowObservation
from devokdev.router.state import (
    UNKNOWN,
    BreakerConfig,
    BreakerState,
    Denied,
    ModelHealth,
    Reservation,
    WindowLimit,
    WindowState,
    breaker_cooldown_ms,
    cost_of,
    to_ms,
)

# Shared Lua helper: a window as it stands now (rolled over if its reset time has passed).
_CURRENT = """
local function current(key, cfg_limit, period, now)
  local h = redis.call('HMGET', key, 'limit', 'remaining', 'resets_at')
  local stored = tonumber(h[1])
  local remaining = tonumber(h[2])
  local resets = tonumber(h[3])
  if (not resets) or now >= resets then
    local limit = cfg_limit
    if stored and stored >= 0 then limit = stored end
    return limit, limit, now + period
  end
  local limit = stored or -1
  if limit < 0 and cfg_limit >= 0 then limit = cfg_limit end
  return limit, remaining or limit, resets
end
"""

# KEYS: window keys. ARGV: now, then per window: configured limit, period, cost.
# Returns {1, resets...} on success, {0, index, resets_at, never_fits} when denied.
_RESERVE = (
    _CURRENT
    + """
local now = tonumber(ARGV[1])
local states = {}
for i = 1, #KEYS do
  local base = 1 + (i - 1) * 3
  local cfg = tonumber(ARGV[base + 1])
  local period = tonumber(ARGV[base + 2])
  local cost = tonumber(ARGV[base + 3])
  local limit, remaining, resets = current(KEYS[i], cfg, period, now)
  if limit >= 0 and cost > limit then return {0, i, tostring(resets), 1} end
  if remaining >= 0 and cost > remaining then return {0, i, tostring(resets), 0} end
  states[i] = {limit, remaining, resets, period, cost}
end
local marks = {1}
for i = 1, #KEYS do
  local s = states[i]
  local left = s[2]
  if left >= 0 then left = left - s[5] end
  redis.call('HSET', KEYS[i], 'limit', s[1], 'remaining', left, 'resets_at', s[3])
  redis.call('PEXPIREAT', KEYS[i], s[3] + s[4])
  marks[#marks + 1] = tostring(s[3])
end
return marks
"""
)

# KEYS: token window keys. ARGV: delta, then the reset mark of each window.
_SETTLE = """
local delta = tonumber(ARGV[1])
for i = 1, #KEYS do
  local h = redis.call('HMGET', KEYS[i], 'remaining', 'resets_at')
  local remaining, resets = tonumber(h[1]), tonumber(h[2])
  if remaining and remaining >= 0 and resets == tonumber(ARGV[i + 1]) then
    redis.call('HSET', KEYS[i], 'remaining', math.max(0, remaining - delta))
  end
end
return 1
"""

# KEYS: one window key. ARGV: now, configured limit, period, obs limit, obs remaining,
# obs reset (ms from now), each -1 when the header did not say.
_OBSERVE = """
local now, cfg, period = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
local olimit, oremaining, oreset = tonumber(ARGV[4]), tonumber(ARGV[5]), tonumber(ARGV[6])
local h = redis.call('HMGET', KEYS[1], 'limit', 'remaining', 'resets_at')
local exists = h[3] ~= false
local limit = olimit
if limit < 0 then limit = exists and tonumber(h[1]) or cfg end
local remaining = oremaining
if remaining < 0 then remaining = exists and tonumber(h[2]) or limit end
local resets
if oreset >= 0 then resets = now + oreset
elseif exists then resets = tonumber(h[3])
else resets = now + period end
redis.call('HSET', KEYS[1], 'limit', limit, 'remaining', remaining, 'resets_at', resets)
redis.call('PEXPIREAT', KEYS[1], resets + period)
return 1
"""

# KEYS: cooldown key. ARGV: until (ms), reason.
_COOL_DOWN = """
local bench_end = tonumber(ARGV[1])  -- 'until' is a reserved word in Lua
local existing = tonumber(redis.call('HGET', KEYS[1], 'until'))
if (not existing) or bench_end > existing then
  redis.call('HSET', KEYS[1], 'until', bench_end, 'reason', ARGV[2])
  redis.call('PEXPIREAT', KEYS[1], bench_end)
end
return 1
"""

# KEYS: breaker key. ARGV: now, trial timeout (ms). Returns 1 if a call may go ahead.
_ALLOW = """
local now, trial = tonumber(ARGV[1]), tonumber(ARGV[2])
local h = redis.call('HMGET', KEYS[1], 'state', 'open_until', 'trial_until')
local state = h[1] or 'closed'
if state == 'closed' then return 1 end
if state == 'open' then
  if now < tonumber(h[2]) then return 0 end
  redis.call('HSET', KEYS[1], 'state', 'half_open', 'trial_until', now + trial)
  return 1
end
if now < tonumber(h[3] or 0) then return 0 end
redis.call('HSET', KEYS[1], 'trial_until', now + trial)
return 1
"""

# KEYS: breaker key. ARGV: now, failures to open, then the cooldown (ms) per trip count
# 1..10 precomputed in Python so the doubling rule lives in one place.
_FAILURE = """
local now, threshold = tonumber(ARGV[1]), tonumber(ARGV[2])
local h = redis.call('HMGET', KEYS[1], 'state', 'failures', 'trips')
local state = h[1] or 'closed'
local failures, trips = tonumber(h[2] or 0), tonumber(h[3] or 0)
if state == 'half_open' or failures + 1 >= threshold then
  trips = trips + 1
  local cooldown = tonumber(ARGV[2 + math.min(trips, 10)])
  redis.call('HSET', KEYS[1], 'state', 'open', 'failures', 0, 'trips', trips,
             'open_until', now + cooldown)
  redis.call('PEXPIRE', KEYS[1], cooldown + 86400000)
  return 'open'
end
redis.call('HSET', KEYS[1], 'state', state, 'failures', failures + 1)
redis.call('PEXPIRE', KEYS[1], 86400000)
return state
"""


def _int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode()
    return int(float(value))


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return value.decode() if isinstance(value, bytes) else str(value)


class RedisRouterState:
    def __init__(
        self,
        client: Redis,
        breaker_config: BreakerConfig | None = None,
        prefix: str = "devokdev:router:",
    ) -> None:
        self._redis = client
        self.breaker_config = breaker_config or BreakerConfig()
        self._prefix = prefix
        self._reserve = client.register_script(_RESERVE)
        self._settle = client.register_script(_SETTLE)
        self._observe = client.register_script(_OBSERVE)
        self._cool_down = client.register_script(_COOL_DOWN)
        self._allow = client.register_script(_ALLOW)
        self._failure = client.register_script(_FAILURE)

    def _wkey(self, w: WindowLimit) -> str:
        return f"{self._prefix}w:{w.key}"

    def _cdkey(self, model_id: str) -> str:
        return f"{self._prefix}cd:{model_id}"

    def _brkey(self, model_id: str) -> str:
        return f"{self._prefix}br:{model_id}"

    async def try_reserve(
        self,
        model_id: str,
        windows: Sequence[WindowLimit],
        requests: int,
        tokens: int,
        now: float,
    ) -> Reservation | Denied:
        if not windows:
            return Reservation(model_id, (), tokens, ())
        args: list[int] = [to_ms(now)]
        for w in windows:
            args += [w.limit, w.period_ms, cost_of(w, requests, tokens)]
        reply = await self._reserve(keys=[self._wkey(w) for w in windows], args=args)
        if _int(reply[0]) == 0:
            window = windows[_int(reply[1]) - 1]
            return Denied(window, _int(reply[2]) / 1000, never_fits=_int(reply[3]) == 1)
        marks = tuple(_int(mark) for mark in reply[1:])
        return Reservation(model_id, tuple(windows), tokens, marks)

    async def settle(self, reservation: Reservation, actual_tokens: int) -> None:
        pairs = [
            (w, mark)
            for w, mark in zip(reservation.windows, reservation.marks, strict=True)
            if w.dimension.value == "tokens"
        ]
        if not pairs:
            return
        delta = actual_tokens - reservation.tokens
        await self._settle(
            keys=[self._wkey(w) for w, _ in pairs], args=[delta, *[m for _, m in pairs]]
        )

    async def observe(
        self, updates: Sequence[tuple[WindowLimit, WindowObservation]], now: float
    ) -> None:
        now_ms = to_ms(now)
        for w, obs in updates:
            await self._observe(
                keys=[self._wkey(w)],
                args=[
                    now_ms,
                    w.limit,
                    w.period_ms,
                    UNKNOWN if obs.limit is None else obs.limit,
                    UNKNOWN if obs.remaining is None else obs.remaining,
                    UNKNOWN if obs.reset_after_s is None else to_ms(obs.reset_after_s),
                ],
            )

    async def window_states(
        self, windows: Sequence[WindowLimit], now: float
    ) -> dict[str, WindowState]:
        now_ms = to_ms(now)
        async with self._redis.pipeline(transaction=False) as pipe:
            for w in windows:
                pipe.hmget(self._wkey(w), ["limit", "remaining", "resets_at"])
            rows = await pipe.execute()
        out: dict[str, WindowState] = {}
        for w, (limit_raw, remaining_raw, resets_raw) in zip(windows, rows, strict=True):
            if resets_raw is None or now_ms >= _int(resets_raw):
                stored = _int(limit_raw, UNKNOWN)
                limit = stored if stored >= 0 else w.limit
                out[w.key] = WindowState(limit, limit, now_ms + w.period_ms)
                continue
            limit = _int(limit_raw, UNKNOWN)
            if limit < 0 and w.limit >= 0:
                limit = w.limit
            out[w.key] = WindowState(limit, _int(remaining_raw, limit), _int(resets_raw))
        return out

    async def cool_down(self, model_id: str, until: float, reason: str) -> None:
        await self._cool_down(keys=[self._cdkey(model_id)], args=[to_ms(until), reason])

    async def health(self, model_ids: Sequence[str]) -> dict[str, ModelHealth]:
        async with self._redis.pipeline(transaction=False) as pipe:
            for model_id in model_ids:
                pipe.hmget(self._cdkey(model_id), ["until", "reason"])
                pipe.hmget(self._brkey(model_id), ["state", "failures", "open_until"])
            rows = await pipe.execute()
        out: dict[str, ModelHealth] = {}
        for i, model_id in enumerate(model_ids):
            until, reason = rows[2 * i]
            state, failures, open_until = rows[2 * i + 1]
            out[model_id] = ModelHealth(
                cooldown_until=_int(until) / 1000,
                cooldown_reason=_str(reason),
                breaker=BreakerState(_str(state, "closed")),
                failures=_int(failures),
                open_until=_int(open_until) / 1000,
            )
        return out

    async def allow_attempt(self, model_id: str, now: float) -> bool:
        trial_ms = to_ms(self.breaker_config.trial_timeout_s)
        reply = await self._allow(keys=[self._brkey(model_id)], args=[to_ms(now), trial_ms])
        return _int(reply) == 1

    async def record_success(self, model_id: str) -> None:
        await self._redis.delete(self._brkey(model_id))

    async def record_failure(self, model_id: str, now: float) -> BreakerState:
        cooldowns = [breaker_cooldown_ms(self.breaker_config, trips) for trips in range(1, 11)]
        reply = await self._failure(
            keys=[self._brkey(model_id)],
            args=[to_ms(now), self.breaker_config.failures_to_open, *cooldowns],
        )
        return BreakerState(_str(reply))

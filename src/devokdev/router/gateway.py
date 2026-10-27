"""The gateway: one call to one named model, with quota and health bookkeeping.

The gateway does not choose models; the router does. The gateway makes sure that every
call, whoever makes it (the router, the fitness check, later the agents), follows the same
steps:

1. Ask the circuit breaker whether the model may be called.
2. Reserve quota in every window the call spends from. No quota, no call.
3. Make the call through the adapter.
4. Write back what was learned: the provider's rate-limit headers, the real token count,
   and success or failure (benches and breaker counts from the failure table).

Because these effects live in shared state, a 429 seen by one agent benches the model for
every agent at once.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from devokdev.config import Settings
from devokdev.llm.adapter import Endpoint, OpenAICompatAdapter
from devokdev.llm.errors import ErrorKind, ProviderError
from devokdev.llm.messages import CompletionRequest, CompletionResult
from devokdev.llm.ratelimits import RateLimitObservation, WindowObservation
from devokdev.llm.registry import ModelSpec, Registry
from devokdev.llm.tokens import estimate_input_tokens
from devokdev.router.actions import action_for
from devokdev.router.policy import SkipReason, expected_tokens, windows_for
from devokdev.router.state import (
    UNKNOWN,
    Denied,
    ModelHealth,
    RouterState,
    WindowLimit,
    WindowState,
)

Clock = Callable[[], float]


class ModelUnavailableNow(Exception):  # noqa: N818  (a condition, not a crash)
    """The model could not be called at all: no key, no quota, or its breaker is open.

    Nothing was sent to the provider. ``until`` says when it might be possible again.
    """

    def __init__(self, model_id: str, reason: SkipReason, detail: str, until: float | None):
        super().__init__(f"{model_id}: {reason.value} {detail}".strip())
        self.model_id = model_id
        self.reason = reason
        self.detail = detail
        self.until = until


@dataclass(frozen=True, slots=True)
class Snapshot:
    health: dict[str, ModelHealth]
    windows: dict[str, WindowState]


class Gateway:
    def __init__(
        self,
        registry: Registry,
        settings: Settings,
        state: RouterState,
        adapter: OpenAICompatAdapter,
        clock: Clock = time.time,
    ) -> None:
        self.registry = registry
        self.settings = settings
        self.state = state
        self.adapter = adapter
        self.clock = clock

    def endpoint(self, model: ModelSpec) -> Endpoint | None:
        provider = self.registry.provider_of(model)
        key = self.registry.api_key(provider, self.settings)
        url = self.registry.base_url(provider, self.settings)
        if key is None or url is None:
            return None
        return Endpoint(provider=provider, base_url=url, api_key=key.get_secret_value())

    def usable_ids(self) -> set[str]:
        return {m.id for m in self.registry.usable_models(self.settings)}

    async def snapshot(self, models: Sequence[ModelSpec]) -> Snapshot:
        windows = [w for m in models for w in windows_for(self.registry, m)]
        health = await self.state.health([m.id for m in models])
        states = await self.state.window_states(windows, self.clock())
        return Snapshot(health, states)

    async def call(
        self, model_id: str, request: CompletionRequest, est_input_tokens: int | None = None
    ) -> CompletionResult:
        model = self.registry.model(model_id)
        endpoint = self.endpoint(model)
        if endpoint is None:
            provider = self.registry.provider_of(model)
            raise ModelUnavailableNow(
                model_id, SkipReason.NO_KEY, f"set {provider.key_setting} in .env", None
            )
        now = self.clock()
        if not await self.state.allow_attempt(model_id, now):
            health = (await self.state.health([model_id]))[model_id]
            raise ModelUnavailableNow(
                model_id, SkipReason.CIRCUIT_OPEN, "breaker open", health.benched_until(now)
            )
        est_input = (
            est_input_tokens if est_input_tokens is not None else estimate_input_tokens(request)
        )
        tokens = expected_tokens(est_input, request.max_output_tokens, model)
        windows = windows_for(self.registry, model)
        reservation = await self.state.try_reserve(model_id, windows, 1, tokens, now)
        if isinstance(reservation, Denied):
            reason = (
                SkipReason.TOO_LARGE_FOR_QUOTA if reservation.never_fits else SkipReason.NO_QUOTA
            )
            until = None if reservation.never_fits else reservation.retry_at
            raise ModelUnavailableNow(model_id, reason, reservation.window.key, until)

        try:
            result, observation = await self.adapter.complete(endpoint, model, request)
        except ProviderError as error:
            await self.state.settle(reservation, 0)  # the request counts; tokens did not
            await self._learn(model, error.rate_limits)
            await self._apply_failure(model, error)
            raise
        await self.state.settle(reservation, result.usage.total_tokens)
        await self._learn(model, observation)
        await self.state.record_success(model_id)
        return result

    async def _learn(self, model: ModelSpec, observation: RateLimitObservation | None) -> None:
        """Store what the provider's headers said, in the window each header describes."""
        if observation is None or not observation.windows:
            return
        provider = self.registry.provider_of(model)
        shared = {(d, w): limit for d, w, limit in provider.shared_limits.windows()}
        own = {(d, w): limit for d, w, limit in model.limits.windows()}
        updates: list[tuple[WindowLimit, WindowObservation]] = []
        for obs in observation.windows:
            key = (obs.dimension, obs.window)
            if key in shared:
                target = WindowLimit(f"provider:{provider.name}", *key, shared[key])
            else:
                target = WindowLimit(f"model:{model.id}", *key, own.get(key, UNKNOWN))
            updates.append((target, obs))
        await self.state.observe(updates, self.clock())

    async def _apply_failure(self, model: ModelSpec, error: ProviderError) -> None:
        action = action_for(error)
        now = self.clock()
        if action.bench_s is not None:
            targets = (
                [m.id for m in self.registry.models.values() if m.provider == model.provider]
                if action.bench_provider
                else [model.id]
            )
            for target in targets:
                await self.state.cool_down(target, now + action.bench_s, error.kind.value)
        if action.breaker_failure:
            await self.state.record_failure(model.id, now)
        elif error.kind is not ErrorKind.INVALID_OUTPUT:
            # The provider answered, so the connection is healthy even if the call was refused.
            await self.state.record_success(model.id)

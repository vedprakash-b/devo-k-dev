"""The router: picks a model for every call, and keeps the call alive when one fails.

An agent opens a ``RouterSession`` for its role and makes calls through it. Each call:

1. **Plans**: the policy ranks every model for this role and request (``policy.rank``).
   The session's current model goes first, so sessions are sticky.
2. **Tries** the best candidate through the gateway.
3. **On failure**, follows the failure table (``actions.py``): retry once for a blip,
   otherwise remember the model as failed for this call and try the next one.
4. **Hands off mid-task.** Because the conversation is canonical, the next model simply
   receives the same messages, converted for its provider. Nothing is lost.
5. **Validates** the answer. Invalid output (unknown tool, broken JSON) gets one repair
   prompt on the same model, then the call moves to another model.
6. **Logs every decision** with a reason code, e.g. ``rate_limited → switched to
   cerebras/gpt-oss-120b``, so mission control and the Scribe can show why.

After a fallback, the session stays on the fallback model and only tries its original
("home") model again at the start of a later call, once ``switch_back_after_s`` has
passed. Switching mid-session costs consistency and prompt-cache hits, so it is never done
just because a slightly better model became free.

If no model can take the call, ``AllModelsUnavailable`` says when the earliest one frees
up, so the caller can park the task until then instead of spinning.
"""

from __future__ import annotations

import asyncio
import json
import random
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

import structlog

from devokdev.llm.errors import ErrorKind, ProviderError
from devokdev.llm.messages import CompletionRequest, CompletionResult, Message
from devokdev.llm.registry import Capability
from devokdev.llm.tokens import estimate_input_tokens
from devokdev.router.actions import action_for
from devokdev.router.gateway import Gateway, ModelUnavailableNow
from devokdev.router.policy import Exclusion, Plan, RouteRequest, rank

log = structlog.get_logger("devokdev.router")

Validator = Callable[[CompletionResult, CompletionRequest], str | None]
Sleep = Callable[[float], Awaitable[None]]


class Event(StrEnum):
    USE = "use"  # a model was chosen for an attempt
    OK = "ok"  # the attempt succeeded
    FAIL = "fail"  # the attempt failed
    SKIP = "skip"  # the model could not be called (no quota, breaker open)
    REPAIR = "repair"  # the answer was invalid; the model was asked to fix it


class Why(StrEnum):
    FIRST_CHOICE = "first_choice"
    STICKY = "sticky"
    SWITCHED_BACK = "switched_back"
    FALLBACK = "fallback"
    RETRY = "retry"


@dataclass(frozen=True, slots=True)
class Decision:
    """One routing step, with a machine-readable reason and a human-readable line."""

    step: int
    event: Event
    model_id: str
    reason: str
    detail: str = ""
    after: str | None = None  # for a fallback: the failure that caused it
    from_model: str | None = None

    def describe(self) -> str:
        if self.event is Event.USE:
            if self.reason == Why.FALLBACK:
                return f"{self.after} → switched to {self.model_id}"
            if self.reason == Why.SWITCHED_BACK:
                return f"cooldown over → switched back to {self.model_id}"
            if self.reason == Why.RETRY:
                return f"{self.after} → retrying {self.model_id} once"
            if self.reason == Why.STICKY:
                return f"staying on {self.model_id}"
            return f"routed to {self.model_id}"
        if self.event is Event.OK:
            return f"{self.model_id} answered"
        if self.event is Event.REPAIR:
            return f"{self.model_id} gave invalid output, asked it to repair: {self.detail}"
        suffix = f" ({self.detail})" if self.detail else ""
        verb = "failed" if self.event is Event.FAIL else "skipped"
        return f"{self.model_id} {verb}: {self.reason}{suffix}"


@dataclass(frozen=True, slots=True)
class RoutedResult:
    result: CompletionResult
    decisions: tuple[Decision, ...]

    @property
    def model_id(self) -> str:
        return self.result.model_id


class AllModelsUnavailable(Exception):  # noqa: N818  (a condition the caller handles)
    """No model can take this call now. Park the task until ``retry_at``, if known."""

    def __init__(
        self,
        role: str,
        retry_at: float | None,
        decisions: tuple[Decision, ...],
        excluded: tuple[Exclusion, ...],
    ) -> None:
        reasons: dict[str, int] = {}
        for e in excluded:
            reasons[e.reason.value] = reasons.get(e.reason.value, 0) + 1
        summary = ", ".join(f"{n} {r}" for r, n in sorted(reasons.items())) or "none configured"
        super().__init__(f"no model available for role {role!r} ({summary})")
        self.role = role
        self.retry_at = retry_at
        self.decisions = decisions
        self.excluded = excluded


def default_validator(result: CompletionResult, request: CompletionRequest) -> str | None:
    """The minimum every answer must meet. Returns a problem to repair, or None."""
    message = result.message
    if not message.content and not message.tool_calls:
        return "the reply was empty"
    known = {t.name for t in request.tools}
    for call in message.tool_calls:
        if call.name not in known:
            names = ", ".join(sorted(known)) or "none"
            return f"tool {call.name!r} does not exist; available tools: {names}"
        try:
            call.parsed_arguments()
        except ValueError as exc:
            return f"arguments for {call.name} are not a valid JSON object ({exc})"
    if request.json_mode and not message.tool_calls:
        try:
            if not isinstance(json.loads(message.content or ""), dict):
                return "the reply must be a single JSON object"
        except json.JSONDecodeError as exc:
            return f"the reply is not valid JSON ({exc.msg})"
    return None


def repair_request(
    request: CompletionRequest, result: CompletionResult, problem: str
) -> CompletionRequest:
    """The original conversation, the invalid answer, and one instruction to fix it."""
    bad = result.message
    shown = bad.content or json.dumps(
        [{"name": c.name, "arguments": c.arguments} for c in bad.tool_calls]
    )
    return request.appended(
        Message.assistant(shown),
        Message.user(
            f"Your previous reply could not be used: {problem}. "
            "Reply again with a corrected answer only."
        ),
    )


@dataclass(frozen=True, slots=True)
class RouterConfig:
    max_attempts: int = 6
    switch_back_after_s: float = 120.0
    retry_backoff_s: float = 1.0


@dataclass
class RouterSession:
    """One agent's conversation with the router. Not shared between agents."""

    router: Router
    role: str
    private_data: bool = False
    avoid_families: frozenset[str] = frozenset()
    needs: frozenset[Capability] = frozenset()
    current: str | None = None
    home: str | None = None
    left_home_at: float | None = None
    step: int = 0
    history: list[Decision] = field(default_factory=list)

    def _preferred(self, now: float) -> tuple[Why, tuple[str, ...]]:
        """Which models to try first: stay put, or try home again once the cooldown passed."""
        if self.current is None:
            return Why.FIRST_CHOICE, ()
        switch_back_due = (
            self.home is not None
            and self.current != self.home
            and self.left_home_at is not None
            and now - self.left_home_at >= self.router.config.switch_back_after_s
        )
        if switch_back_due and self.home is not None:
            return Why.SWITCHED_BACK, (self.home, self.current)
        return Why.STICKY, (self.current,)

    def _record(self, decision: Decision) -> Decision:
        self.history.append(decision)
        log.info(
            "router.decision",
            role=self.role,
            step=decision.step,
            decision_event=decision.event.value,
            model=decision.model_id,
            reason=decision.reason,
            line=decision.describe(),
        )
        return decision

    def _on_success(self, model_id: str, now: float) -> None:
        if self.home is None:
            self.home = model_id
        if model_id == self.home:
            self.left_home_at = None
        elif self.current == self.home or self.left_home_at is None:
            self.left_home_at = now
        self.current = model_id

    async def complete(
        self, request: CompletionRequest, validate: Validator | None = default_validator
    ) -> RoutedResult:
        router = self.router
        gateway = router.gateway
        self.step += 1
        decisions: list[Decision] = []

        def record(decision: Decision) -> None:
            decisions.append(self._record(decision))

        first_why, preferred = self._preferred(gateway.clock())
        avoid: set[str] = set()
        retried: set[str] = set()
        repaired: set[str] = set()
        min_context = 0
        working = request  # the request actually sent; differs during a repair
        pinned: tuple[str, ...] = preferred
        why: Why = first_why
        after: str | None = None
        last_failed: str | None = None
        excluded: tuple[Exclusion, ...] = ()

        for _ in range(router.config.max_attempts):
            plan = await router.plan(
                RouteRequest(
                    role=self.role,
                    est_input_tokens=estimate_input_tokens(working),
                    max_output_tokens=working.max_output_tokens,
                    needs=self.needs | _needs_of(working),
                    private_data=self.private_data,
                    avoid_families=self.avoid_families,
                    avoid_models=frozenset(avoid),
                    min_context=min_context,
                    preferred=pinned,
                )
            )
            excluded = plan.excluded
            if not plan.candidates:
                break
            model = plan.candidates[0].model
            if pinned and model.id != pinned[0]:
                # The model we meant to use is not available; say why we moved.
                if why is Why.SWITCHED_BACK and model.id == self.current:
                    why = Why.STICKY
                else:
                    missed = next((e for e in plan.excluded if e.model_id == pinned[0]), None)
                    after = after or (missed.reason.value if missed else None)
                    last_failed = last_failed or pinned[0]
                    why = Why.FALLBACK
            record(
                Decision(self.step, Event.USE, model.id, why, after=after, from_model=last_failed)
            )

            try:
                result = await gateway.call(
                    model.id, working, est_input_tokens=estimate_input_tokens(working)
                )
            except ModelUnavailableNow as unavailable:
                record(
                    Decision(
                        self.step,
                        Event.SKIP,
                        model.id,
                        unavailable.reason.value,
                        unavailable.detail,
                    )
                )
                avoid.add(model.id)
                why, after, last_failed, pinned = (
                    Why.FALLBACK,
                    unavailable.reason.value,
                    model.id,
                    (),
                )
                continue
            except ProviderError as error:
                record(Decision(self.step, Event.FAIL, model.id, error.kind.value, error.message))
                action = action_for(error)
                if action.retry_same_once and model.id not in retried:
                    retried.add(model.id)
                    await router.sleep(router.config.retry_backoff_s * router.rng.uniform(0.5, 1.5))
                    why, after, pinned = Why.RETRY, error.kind.value, (model.id,)
                    continue
                if action.grow_context:
                    min_context = max(min_context, model.context_window + 1)
                avoid.add(model.id)
                working = request  # a repair conversation is not carried to another model
                why, after, last_failed, pinned = Why.FALLBACK, error.kind.value, model.id, ()
                continue

            problem = validate(result, working) if validate is not None else None
            if problem is not None:
                if model.id not in repaired:
                    repaired.add(model.id)
                    record(
                        Decision(
                            self.step,
                            Event.REPAIR,
                            model.id,
                            ErrorKind.INVALID_OUTPUT.value,
                            problem,
                        )
                    )
                    working = repair_request(request, result, problem)
                    why, after, pinned = Why.RETRY, ErrorKind.INVALID_OUTPUT.value, (model.id,)
                    continue
                record(
                    Decision(
                        self.step, Event.FAIL, model.id, ErrorKind.INVALID_OUTPUT.value, problem
                    )
                )
                avoid.add(model.id)
                working = request
                why, after, last_failed, pinned = (
                    Why.FALLBACK,
                    ErrorKind.INVALID_OUTPUT.value,
                    model.id,
                    (),
                )
                continue

            record(Decision(self.step, Event.OK, model.id, "ok"))
            self._on_success(model.id, gateway.clock())
            return RoutedResult(result, tuple(decisions))

        retry_at = Plan((), excluded).earliest_retry
        raise AllModelsUnavailable(self.role, retry_at, tuple(decisions), excluded)


def _needs_of(request: CompletionRequest) -> frozenset[Capability]:
    needs: set[Capability] = set()
    if request.tools:
        needs.add(Capability.TOOLS)
    return frozenset(needs)


class Router:
    def __init__(
        self,
        gateway: Gateway,
        config: RouterConfig | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.gateway = gateway
        self.config = config or RouterConfig()
        self.sleep = sleep
        self.rng = rng or random.Random()  # noqa: S311 (jitter, not security)

    def session(
        self,
        role: str,
        *,
        private_data: bool = False,
        avoid_families: Iterable[str] = (),
        needs: Iterable[Capability] = (),
    ) -> RouterSession:
        self.gateway.registry.role(role)  # fail fast on a typo
        return RouterSession(
            self,
            role,
            private_data=private_data,
            avoid_families=frozenset(avoid_families),
            needs=frozenset(needs),
        )

    async def plan(self, request: RouteRequest) -> Plan:
        registry = self.gateway.registry
        models = list(registry.models.values())
        snapshot = await self.gateway.snapshot(models)
        return rank(
            registry,
            request,
            self.gateway.usable_ids(),
            snapshot.health,
            snapshot.windows,
            self.gateway.clock(),
        )

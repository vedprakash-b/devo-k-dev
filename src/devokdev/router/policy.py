"""Routing policy v1: signals in, an ordered list of candidates out.

The design separates *signals* (facts about the request and the providers) from *policy*
(rules that turn facts into a choice), an idea from the vLLM Semantic Router paper. Here
the signals are a ``RouteRequest`` plus a snapshot of quota and health, and the policy is
a pure function with no I/O, so every rule is unit-tested without a network or a clock.

The rules, in order:

1. **Filter.** Drop every model that cannot take this call, and record why: no key, no
   tier for the role, a missing capability, a context window that is too small, a data
   policy that forbids private data, the author's model family (for reviewers), a failure
   earlier in this task, a cooldown, an open circuit breaker, or no quota left.
2. **Rank.** Preferred models first (the session's current model, which keeps sessions
   sticky), then higher quality tier for the role, then more quota headroom, then
   providers that do not train on prompts, then by name so the order is deterministic.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from devokdev.llm.ratelimits import Dimension
from devokdev.llm.registry import Capability, Limits, ModelSpec, Registry, RoleSpec
from devokdev.router.state import UNKNOWN, ModelHealth, WindowLimit, WindowState, cost_of

CONTEXT_SAFETY = 1.1  # token estimates are approximate; leave 10% spare
EXPECTED_OUTPUT_CAP = 1024  # tokens reserved for the answer before its real size is known


class SkipReason(StrEnum):
    NO_KEY = "no_key"
    ROLE_NOT_SUPPORTED = "role_not_supported"
    MISSING_CAPABILITY = "missing_capability"
    CONTEXT_TOO_SMALL = "context_too_small"
    DATA_POLICY = "trains_on_prompts"
    SAME_FAMILY = "same_family"
    FAILED_THIS_TASK = "failed_this_task"
    COOLING_DOWN = "cooling_down"
    CIRCUIT_OPEN = "circuit_open"
    NO_QUOTA = "no_quota"
    TOO_LARGE_FOR_QUOTA = "too_large_for_quota"


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """The signals for one call."""

    role: str
    est_input_tokens: int
    max_output_tokens: int
    needs: frozenset[Capability] = frozenset()
    private_data: bool = False  # private code may only go to providers that do not train
    avoid_families: frozenset[str] = frozenset()  # e.g. the author's family, for reviewers
    avoid_models: frozenset[str] = frozenset()  # failed earlier in this task
    min_context: int = 0  # raised after a context-length error
    preferred: tuple[str, ...] = ()  # stickiness: try these first, in this order


@dataclass(frozen=True, slots=True)
class Candidate:
    model: ModelSpec
    tier: int
    headroom: float  # least fraction of quota left across its windows; 1.0 if unknown


@dataclass(frozen=True, slots=True)
class Exclusion:
    model_id: str
    reason: SkipReason
    detail: str = ""
    until: float | None = None  # when this model could be eligible again, if known


@dataclass(frozen=True, slots=True)
class Plan:
    candidates: tuple[Candidate, ...]
    excluded: tuple[Exclusion, ...] = field(default=())

    @property
    def earliest_retry(self) -> float | None:
        times = [e.until for e in self.excluded if e.until is not None]
        return min(times) if times else None


def windows_for(registry: Registry, model: ModelSpec) -> list[WindowLimit]:
    """Every quota window a call to this model spends from: its own and its provider's."""

    def build(scope: str, limits: Limits) -> list[WindowLimit]:
        return [WindowLimit(scope, dim, win, limit) for dim, win, limit in limits.windows()]

    provider = registry.provider_of(model)
    return build(f"model:{model.id}", model.limits) + build(
        f"provider:{provider.name}", provider.shared_limits
    )


def expected_tokens(est_input: int, max_output: int, model: ModelSpec) -> int:
    """Tokens to reserve before the call: the prompt plus a capped guess at the answer."""
    return est_input + min(max_output, model.max_output_tokens, EXPECTED_OUTPUT_CAP)


def _effective_limit(window: WindowLimit, state: WindowState | None) -> int:
    if state is not None and state.limit >= 0:
        return state.limit
    return window.limit


def _quota_check(
    windows: Sequence[WindowLimit],
    states: Mapping[str, WindowState],
    tokens: int,
) -> tuple[float, Exclusion | None, str]:
    """Headroom, plus an exclusion if this call cannot fit right now."""
    headroom = 1.0
    for w in windows:
        state = states.get(w.key)
        cost = cost_of(w, 1, tokens)
        limit = _effective_limit(w, state)
        if limit != UNKNOWN and cost > limit:
            dim = "tokens" if w.dimension is Dimension.TOKENS else "requests"
            detail = f"needs {cost} {dim}, limit is {limit}/{w.window.value}"
            return 0.0, Exclusion("", SkipReason.TOO_LARGE_FOR_QUOTA, detail), w.key
        if state is None:
            continue
        if state.remaining != UNKNOWN and cost > state.remaining:
            detail = f"{w.key} has {state.remaining} left"
            until = state.resets_at_ms / 1000
            return 0.0, Exclusion("", SkipReason.NO_QUOTA, detail, until), w.key
        fraction = state.fraction_left
        if fraction is not None:
            headroom = min(headroom, fraction)
    return headroom, None, ""


def judge(
    registry: Registry,
    model: ModelSpec,
    request: RouteRequest,
    usable: Collection[str],
    health: Mapping[str, ModelHealth],
    window_states: Mapping[str, WindowState],
    now: float,
) -> Candidate | Exclusion:
    """Decide whether one model can take this call, and why not if it can't."""
    role: RoleSpec = registry.role(request.role)
    tier = model.tier(role.role_class)
    output = min(request.max_output_tokens, model.max_output_tokens)
    min_context = max(request.min_context, role.min_context)
    required_context = max(min_context, int(request.est_input_tokens * CONTEXT_SAFETY) + output)
    missing = sorted(c.value for c in set(request.needs) | set(role.needs) if not model.has(c))

    def skip(reason: SkipReason, detail: str = "", until: float | None = None) -> Exclusion:
        return Exclusion(model.id, reason, detail, until)

    if model.id not in usable:
        return skip(SkipReason.NO_KEY, f"set {registry.provider_of(model).key_setting} in .env")
    if tier == 0:
        return skip(SkipReason.ROLE_NOT_SUPPORTED, f"no tier for {role.role_class.value}")
    if missing:
        return skip(SkipReason.MISSING_CAPABILITY, ", ".join(missing))
    if model.context_window < required_context:
        detail = f"needs {required_context} tokens, has {model.context_window}"
        return skip(SkipReason.CONTEXT_TOO_SMALL, detail)
    if request.private_data and model.trains_on_prompts:
        return skip(SkipReason.DATA_POLICY, "private data never goes to a provider that trains")
    if model.family in request.avoid_families:
        return skip(SkipReason.SAME_FAMILY, model.family)
    # Shared, time-bound facts come before the per-call exclusion, so a caller who runs out
    # of models still learns when the earliest one will be back.
    state = health.get(model.id, ModelHealth())
    benched = state.benched_until(now)
    if benched is not None:
        if state.cooldown_until > now:
            return skip(SkipReason.COOLING_DOWN, state.cooldown_reason, benched)
        return skip(SkipReason.CIRCUIT_OPEN, "repeated failures", benched)
    if model.id in request.avoid_models:
        return skip(SkipReason.FAILED_THIS_TASK)
    tokens = expected_tokens(request.est_input_tokens, request.max_output_tokens, model)
    headroom, problem, _ = _quota_check(windows_for(registry, model), window_states, tokens)
    if problem is not None:
        return skip(problem.reason, problem.detail, problem.until)
    return Candidate(model, tier, headroom)


def rank(
    registry: Registry,
    request: RouteRequest,
    usable: Collection[str],
    health: Mapping[str, ModelHealth],
    window_states: Mapping[str, WindowState],
    now: float,
) -> Plan:
    """Every model judged, the usable ones ordered best first."""
    registry.role(request.role)  # fail fast on an unknown role
    candidates: list[Candidate] = []
    excluded: list[Exclusion] = []
    for model in registry.models.values():
        verdict = judge(registry, model, request, usable, health, window_states, now)
        if isinstance(verdict, Candidate):
            candidates.append(verdict)
        else:
            excluded.append(verdict)

    preferred = {model_id: i for i, model_id in enumerate(request.preferred)}

    def order(c: Candidate) -> tuple[int, int, float, bool, str]:
        return (
            preferred.get(c.model.id, len(preferred)),
            -c.tier,
            -round(c.headroom, 1),  # 0.1 steps, so tiny differences don't flip choices
            c.model.trains_on_prompts,
            c.model.id,
        )

    return Plan(tuple(sorted(candidates, key=order)), tuple(excluded))

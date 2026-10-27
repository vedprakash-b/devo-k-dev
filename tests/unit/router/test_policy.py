"""The routing policy is a pure function: every rule is tested with plain data."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from devokdev.llm.ratelimits import Dimension, Window
from devokdev.llm.registry import Capability
from devokdev.router.policy import RouteRequest, SkipReason, rank, windows_for
from devokdev.router.state import BreakerState, ModelHealth, WindowLimit, WindowState
from tests.support import TEST_REGISTRY_YAML, make_registry

NOW = 1_800_000_000.0
REGISTRY = make_registry()
ALL = {"alpha/alpha-large", "alpha/alpha-small", "beta/beta-coder"}


def plan_for(
    request: RouteRequest,
    usable: set[str] = ALL,
    health: Mapping[str, ModelHealth] | None = None,
    windows: Mapping[str, WindowState] | None = None,
) -> tuple[list[str], dict[str, SkipReason]]:
    plan = rank(REGISTRY, request, usable, health or {}, windows or {}, NOW)
    return [c.model.id for c in plan.candidates], {e.model_id: e.reason for e in plan.excluded}


def req(role: str = "backend", **kw: object) -> RouteRequest:
    values: dict[str, object] = {"est_input_tokens": 500, "max_output_tokens": 1000}
    values.update(kw)
    return RouteRequest(role=role, **values)  # type: ignore[arg-type]


def test_candidates_are_ordered_by_tier_for_the_role() -> None:
    order, _ = plan_for(req("backend"))
    assert order == ["alpha/alpha-large", "beta/beta-coder", "alpha/alpha-small"]
    order, _ = plan_for(req("scribe"))
    assert order[0] == "alpha/alpha-small"  # light tier 4 beats the large model's 2


def test_preferred_models_come_first_so_sessions_stay_sticky() -> None:
    order, _ = plan_for(req(preferred=("beta/beta-coder",)))
    assert order[0] == "beta/beta-coder"


def test_models_without_a_key_are_excluded_with_a_hint() -> None:
    plan = rank(REGISTRY, req(), {"beta/beta-coder"}, {}, {}, NOW)
    reasons = {e.model_id: (e.reason, e.detail) for e in plan.excluded}
    assert reasons["alpha/alpha-large"] == (SkipReason.NO_KEY, "set groq_api_key in .env")


def test_role_capabilities_are_required() -> None:
    beta_tools = "        tools: true\n        json_mode: true\n        tiers: {coding: 4"
    assert beta_tools in TEST_REGISTRY_YAML
    text = TEST_REGISTRY_YAML.replace(beta_tools, beta_tools.replace("tools: true\n        ", ""))
    registry = make_registry(text)
    plan = rank(registry, req("backend"), ALL, {}, {}, NOW)
    assert {e.model_id: e.reason for e in plan.excluded}["beta/beta-coder"] is (
        SkipReason.MISSING_CAPABILITY
    )


def test_conversations_that_do_not_fit_skip_small_models() -> None:
    order, excluded = plan_for(req(est_input_tokens=40_000, max_output_tokens=1000))
    assert "alpha/alpha-small" not in order
    assert excluded["alpha/alpha-small"] is SkipReason.CONTEXT_TOO_SMALL
    order, _ = plan_for(req(min_context=70_000))
    assert order == ["alpha/alpha-large"]


def test_a_role_minimum_context_applies_to_every_call() -> None:
    order, _ = plan_for(req("researcher", est_input_tokens=100))
    assert order == ["alpha/alpha-large"]  # min_context 100k


def test_private_data_never_reaches_a_provider_that_trains() -> None:
    order, excluded = plan_for(req(private_data=True))
    assert "beta/beta-coder" not in order
    assert excluded["beta/beta-coder"] is SkipReason.DATA_POLICY


def test_reviewers_avoid_the_authors_model_family() -> None:
    order, excluded = plan_for(req("reviewer", avoid_families=frozenset({"fam-a"})))
    assert order == ["beta/beta-coder"]
    assert excluded["alpha/alpha-large"] is SkipReason.SAME_FAMILY


def test_models_that_failed_this_task_are_skipped() -> None:
    order, excluded = plan_for(req(avoid_models=frozenset({"alpha/alpha-large"})))
    assert order[0] == "beta/beta-coder"
    assert excluded["alpha/alpha-large"] is SkipReason.FAILED_THIS_TASK


def test_benched_models_report_when_they_return() -> None:
    health = {
        "alpha/alpha-large": ModelHealth(cooldown_until=NOW + 30, cooldown_reason="rate_limited"),
        "beta/beta-coder": ModelHealth(breaker=BreakerState.OPEN, open_until=NOW + 60),
    }
    plan = rank(REGISTRY, req(), ALL, health, {}, NOW)
    reasons = {e.model_id: (e.reason, e.until) for e in plan.excluded}
    assert reasons["alpha/alpha-large"] == (SkipReason.COOLING_DOWN, NOW + 30)
    assert reasons["beta/beta-coder"] == (SkipReason.CIRCUIT_OPEN, NOW + 60)
    assert [c.model.id for c in plan.candidates] == ["alpha/alpha-small"]
    assert plan.earliest_retry == NOW + 30


def test_an_expired_breaker_lets_the_model_back_in_for_a_trial() -> None:
    health = {"alpha/alpha-large": ModelHealth(breaker=BreakerState.OPEN, open_until=NOW - 1)}
    order, _ = plan_for(req(), health=health)
    assert order[0] == "alpha/alpha-large"


def test_no_quota_left_excludes_until_the_window_resets() -> None:
    rpm = WindowLimit("model:alpha/alpha-large", Dimension.REQUESTS, Window.MINUTE, 30)
    windows = {rpm.key: WindowState(30, 0, int((NOW + 20) * 1000))}
    plan = rank(REGISTRY, req(), ALL, {}, windows, NOW)
    excluded = {e.model_id: e for e in plan.excluded}
    assert excluded["alpha/alpha-large"].reason is SkipReason.NO_QUOTA
    assert excluded["alpha/alpha-large"].until == pytest.approx(NOW + 20)


def test_a_call_larger_than_a_token_limit_can_never_fit() -> None:
    order, excluded = plan_for(req(est_input_tokens=9000, max_output_tokens=100))
    assert excluded["alpha/alpha-large"] is SkipReason.TOO_LARGE_FOR_QUOTA  # tpm is 8000
    assert "beta/beta-coder" in order


def test_more_headroom_wins_between_equal_tiers() -> None:
    text = TEST_REGISTRY_YAML.replace("tiers: {coding: 5,", "tiers: {coding: 4,")
    registry = make_registry(text)
    rpd = WindowLimit("model:alpha/alpha-large", Dimension.REQUESTS, Window.DAY, 1000)
    windows = {rpd.key: WindowState(1000, 50, int((NOW + 3600) * 1000))}
    plan = rank(registry, req(), ALL, {}, windows, NOW)
    assert plan.candidates[0].model.id == "beta/beta-coder"  # 100% left beats 5% left


def test_windows_include_the_providers_shared_limits() -> None:
    windows = windows_for(REGISTRY, REGISTRY.model("beta/beta-coder"))
    assert {w.key for w in windows} == {
        "provider:beta|requests|minute",
        "provider:beta|requests|day",
    }


def test_extra_capabilities_from_the_call_are_required_too() -> None:
    order, _ = plan_for(req("scribe", needs=frozenset({Capability.JSON})))
    assert "alpha/alpha-small" not in order  # no json mode


def test_unknown_roles_fail_fast() -> None:
    with pytest.raises(KeyError, match="unknown role"):
        plan_for(req("chef"))

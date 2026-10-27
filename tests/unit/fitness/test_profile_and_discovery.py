from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from devokdev.fitness.discovery import discover
from devokdev.fitness.profile import ProfileStore, profile_model
from devokdev.llm.scripted import Reply, ScriptedTransport
from devokdev.router.factory import open_router
from tests.support import TEST_REGISTRY_YAML, FakeClock, make_registry, make_settings

GOOD_ANSWERS = [
    Reply(text="ALPHA\nseven\nOMEGA"),
    Reply(text='{"name": "Asha", "languages": ["a", "b", "c"], "years_experience": 4}'),
    Reply(tool_calls=(("get_weather", {"city": "Bengaluru", "unit": "celsius"}),)),
    Reply(text="KESAR-4207"),
]


async def run_profile(transport: ScriptedTransport, model_id: str, clock: FakeClock | None = None):  # type: ignore[no-untyped-def]
    clock = clock or FakeClock()
    async with open_router(
        make_settings(),
        registry=make_registry(),
        transport=transport,
        use_redis=False,
        clock=clock,
        sleep=clock.sleep,
    ) as ctx:
        return await profile_model(ctx.gateway, model_id, "quick", None, sleep=clock.sleep)


async def test_a_good_model_gets_an_ok_profile() -> None:
    transport = ScriptedTransport({"beta-coder": [*GOOD_ANSWERS, Reply(text="KESAR-4320")]})
    profile = await run_profile(transport, "beta/beta-coder")
    assert profile.status == "ok"
    assert profile.score("instructions") == 1.0
    assert profile.score("json") == 1.0
    assert profile.score("tool_call") == 1.0
    assert profile.score("code_fix") is None  # no sandbox in unit tests
    assert profile.score("recall") == 1.0
    assert profile.overall == 1.0
    assert profile.ttft_ms is not None


async def test_profiling_waits_for_a_per_minute_window_instead_of_giving_up() -> None:
    text = TEST_REGISTRY_YAML.replace("limits: {rpm: 30, rpd: 1000, tpm: 8000}", "limits: {rpm: 2}")
    clock = FakeClock()
    transport = ScriptedTransport({"alpha-large": [*GOOD_ANSWERS]})
    async with open_router(
        make_settings(), registry=make_registry(text), transport=transport,
        use_redis=False, clock=clock, sleep=clock.sleep,
    ) as ctx:  # fmt: skip
        profile = await profile_model(ctx.gateway, "alpha/alpha-large", "quick", None, clock.sleep)
    assert profile.status == "ok"
    assert clock.slept  # it waited for the minute to roll over
    assert transport.calls_to("alpha-large") == 5  # four probes, two recall lengths


async def test_a_bad_key_stops_profiling_without_scoring_the_model_down() -> None:
    transport = ScriptedTransport({"beta-coder": [Reply(status=401, error_body="bad key")]})
    profile = await run_profile(transport, "beta/beta-coder")
    assert profile.status == "failed"
    assert all(p.score is None for p in profile.probes)
    assert transport.calls_to("beta-coder") == 1


async def test_a_transient_error_leaves_a_probe_unmeasured() -> None:
    answers = [GOOD_ANSWERS[0], Reply.server_error(), Reply.server_error(), *GOOD_ANSWERS[2:]]
    profile = await run_profile(ScriptedTransport({"beta-coder": answers}), "beta/beta-coder")
    assert profile.score("json") is None
    assert profile.score("tool_call") == 1.0
    assert profile.status == "ok"


def test_profiles_are_cached_until_stale(tmp_path: Path) -> None:
    from devokdev.fitness.probes import SUITE_VERSION
    from devokdev.fitness.profile import ModelProfile

    store = ProfileStore(tmp_path)
    now = datetime.now(UTC)
    profile = ModelProfile(
        model_id="alpha/alpha-large",
        fingerprint="abc",
        suite_version=SUITE_VERSION,
        depth="quick",
        profiled_at=now,
        status="ok",
        probes=(),
    )
    path = store.save(profile)
    assert path.name == "alpha_alpha-large.json"
    loaded = store.load("alpha/alpha-large")
    assert loaded == profile
    assert loaded.is_fresh("abc", now)
    assert not loaded.is_fresh("changed-entry", now)
    assert not loaded.is_fresh("abc", now + timedelta(days=15))
    path.write_text("{ broken")
    assert store.load("alpha/alpha-large") is None


async def test_discovery_reports_missing_and_new_models() -> None:
    text = TEST_REGISTRY_YAML.replace(
        "    shared_limits: {rpm: 20, rpd: 50}\n",
        '    shared_limits: {rpm: 20, rpd: 50}\n    discovery_match: ":free$"\n',
    )
    transport = ScriptedTransport(
        models_by_host={
            "alpha.test": ["models/alpha-large", "alpha-xl"],
            "beta.test": ["beta-coder", "beta-new:free", "beta-paid"],
        }
    )
    async with open_router(
        make_settings(), registry=make_registry(text), transport=transport, use_redis=False
    ) as ctx:
        reports = {r.provider: r for r in await discover(ctx.gateway)}
    alpha, beta = reports["alpha"], reports["beta"]
    assert alpha.status == "ok"
    assert alpha.missing == ("alpha-small",)  # renamed or withdrawn
    assert alpha.new == ("alpha-xl",)
    assert "alpha-large" in alpha.served  # the "models/" prefix is removed
    assert beta.new == ("beta-new:free",)  # the filter hides paid models


async def test_discovery_skips_providers_without_keys() -> None:
    from pydantic import SecretStr

    async with open_router(
        make_settings(cerebras_api_key=SecretStr("")),
        registry=make_registry(),
        transport=ScriptedTransport(models_by_host={"alpha.test": ["alpha-large"]}),
        use_redis=False,
    ) as ctx:
        reports = {r.provider: r for r in await discover(ctx.gateway)}
    assert reports["beta"].status == "no_key"


@pytest.mark.parametrize("status", [401, 503])
async def test_discovery_errors_are_reported_not_raised(status: int) -> None:
    class Failing(ScriptedTransport):
        async def handle_async_request(self, request):  # type: ignore[no-untyped-def]
            import httpx

            return httpx.Response(status, text="nope")

    async with open_router(
        make_settings(), registry=make_registry(), transport=Failing(), use_redis=False
    ) as ctx:
        reports = await discover(ctx.gateway)
    assert {r.status for r in reports} == {"error"}

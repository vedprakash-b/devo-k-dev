"""The router end to end: real adapter, real policy, scripted providers, fake clock.

The first test is M1's definition of done: the router survives a 429 in the middle of a
conversation, hands the conversation to another model, and finishes the task.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic import SecretStr

from devokdev.llm.messages import CompletionRequest, Message, ToolSpec
from devokdev.llm.scripted import Reply, ScriptedTransport
from devokdev.router.factory import RouterContext, open_router
from devokdev.router.policy import SkipReason
from devokdev.router.router import AllModelsUnavailable, Event, Why
from devokdev.router.state import BreakerState
from tests.support import FakeClock, make_registry, make_settings

LIST_DIR = ToolSpec(
    name="list_dir",
    description="List the files in a directory",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


@asynccontextmanager
async def routed(
    transport: ScriptedTransport, clock: FakeClock | None = None, **settings: Any
) -> AsyncIterator[RouterContext]:
    clock = clock or FakeClock()
    async with open_router(
        make_settings(**settings),
        registry=make_registry(),
        transport=transport,
        use_redis=False,
        clock=clock,
        sleep=clock.sleep,
    ) as ctx:
        yield ctx


def ask(text: str, tools: bool = True) -> CompletionRequest:
    return CompletionRequest(
        messages=(Message.system("You are the backend engineer."), Message.user(text)),
        tools=(LIST_DIR,) if tools else (),
    )


def lines(decisions: tuple[Any, ...]) -> list[str]:
    return [d.describe() for d in decisions]


async def test_a_429_mid_conversation_hands_the_conversation_to_another_model() -> None:
    transport = ScriptedTransport(
        {
            "alpha-large": [
                Reply(tool_calls=(("list_dir", {"path": "src"}),)),
                Reply.rate_limited(retry_after_s=30),
            ],
            "beta-coder": [Reply(text="src holds the devokdev package.")],
        }
    )
    clock = FakeClock()
    async with routed(transport, clock) as ctx:
        session = ctx.router.session("backend")

        # Turn 1: the best model for the role asks to run a tool.
        first = await session.complete(ask("What is in src?"))
        assert first.model_id == "alpha/alpha-large"
        call = first.result.message.tool_calls[0]

        # Turn 2: the conversation continues; alpha is rate limited mid-task.
        conversation = ask("What is in src?").appended(
            first.result.message, Message.tool_result(call, "devokdev/")
        )
        second = await session.complete(conversation)

    assert second.model_id == "beta/beta-coder"
    assert second.result.message.content == "src holds the devokdev package."
    assert "rate_limited → switched to beta/beta-coder" in lines(second.decisions)

    # The handoff carried the whole conversation, tool call and result included.
    host, payload = transport.requests[-1]
    assert host == "beta.test"
    roles = [m["role"] for m in payload["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert payload["messages"][2]["tool_calls"][0]["id"] == call.id
    assert payload["messages"][3]["tool_call_id"] == call.id

    # The rate-limited model is benched for its retry-after, for everyone.
    health = (await ctx.gateway.state.health(["alpha/alpha-large"]))["alpha/alpha-large"]
    assert health.cooldown_reason == "rate_limited"
    assert health.cooldown_until == pytest.approx(clock.now + 30)


async def test_sessions_stay_on_the_fallback_then_switch_back_after_the_cooldown() -> None:
    transport = ScriptedTransport(
        {
            "alpha-large": [Reply(text="one"), Reply.rate_limited(10), Reply(text="four")],
            "beta-coder": [Reply(text="two"), Reply(text="three")],
        }
    )
    clock = FakeClock()
    async with routed(transport, clock, router_switch_back_after_s=120) as ctx:
        session = ctx.router.session("backend")
        assert (await session.complete(ask("1"))).model_id == "alpha/alpha-large"
        assert (await session.complete(ask("2"))).model_id == "beta/beta-coder"
        clock.advance(60)  # alpha's cooldown is over, but the session stays put
        third = await session.complete(ask("3"))
        assert third.model_id == "beta/beta-coder"
        assert "staying on beta/beta-coder" in lines(third.decisions)
        clock.advance(61)  # now past switch_back_after_s
        fourth = await session.complete(ask("4"))
    assert fourth.model_id == "alpha/alpha-large"
    assert fourth.decisions[0].reason == Why.SWITCHED_BACK


async def test_a_server_blip_is_retried_once_on_the_same_model() -> None:
    transport = ScriptedTransport({"alpha-large": [Reply.server_error(503), Reply(text="ok")]})
    clock = FakeClock()
    async with routed(transport, clock) as ctx:
        routed_result = await ctx.router.session("backend").complete(ask("hi"))
    assert routed_result.model_id == "alpha/alpha-large"
    assert transport.calls_to("alpha-large") == 2
    assert len(clock.slept) == 1
    assert 0.5 <= clock.slept[0] <= 1.5  # jittered backoff
    assert "server_error → retrying alpha/alpha-large once" in lines(routed_result.decisions)


async def test_repeated_server_errors_switch_models_and_count_toward_the_breaker() -> None:
    transport = ScriptedTransport(
        {"alpha-large": [Reply.server_error(500)], "beta-coder": [Reply(text="ok")]}
    )
    async with routed(transport, router_breaker_failures=2) as ctx:
        result = await ctx.router.session("backend").complete(ask("hi"))
        health = (await ctx.gateway.state.health(["alpha/alpha-large"]))["alpha/alpha-large"]
    assert result.model_id == "beta/beta-coder"
    assert health.breaker is BreakerState.OPEN


async def test_a_hung_stream_is_abandoned_and_the_next_model_answers() -> None:
    transport = ScriptedTransport(
        {"alpha-large": [Reply.hung(30)], "beta-coder": [Reply(text="fast answer")]}
    )
    async with routed(transport, router_first_token_timeout_s=0.05) as ctx:
        result = await ctx.router.session("backend").complete(ask("hi"))
    assert result.model_id == "beta/beta-coder"
    assert "hung_stream → switched to beta/beta-coder" in lines(result.decisions)


async def test_a_context_length_error_moves_to_a_model_with_a_bigger_window() -> None:
    too_long = Reply(status=400, error_body="This model's maximum context length is 32768 tokens")
    transport = ScriptedTransport(
        {"alpha-small": [too_long], "beta-coder": [Reply(text="summary")]}
    )
    async with routed(transport) as ctx:
        result = await ctx.router.session("scribe").complete(ask("summarise", tools=False))
    assert result.model_id == "beta/beta-coder"  # 65k window, next best for light work


async def test_invalid_output_gets_one_repair_on_the_same_model() -> None:
    transport = ScriptedTransport(
        {"alpha-large": [Reply(tool_calls=(("delete_everything", {}),)), Reply(text="fixed")]}
    )
    async with routed(transport) as ctx:
        result = await ctx.router.session("backend").complete(ask("hi"))
    assert result.model_id == "alpha/alpha-large"
    assert result.result.message.content == "fixed"
    events = [d.event for d in result.decisions]
    assert Event.REPAIR in events
    repair_payload = transport.requests[-1][1]
    assert "could not be used" in repair_payload["messages"][-1]["content"]
    assert "delete_everything" in repair_payload["messages"][-1]["content"]


async def test_output_still_invalid_after_repair_moves_to_another_model() -> None:
    bad = Reply(text="not json")
    transport = ScriptedTransport(
        {"alpha-large": [bad], "beta-coder": [Reply(text='{"ok": true}')]}
    )
    request = ask("answer in JSON", tools=False).model_copy(update={"json_mode": True})
    async with routed(transport) as ctx:
        result = await ctx.router.session("backend").complete(request)
    assert result.model_id == "beta/beta-coder"
    # the repair conversation was not carried over to the next model
    assert len(transport.requests[-1][1]["messages"]) == 2


async def test_a_bad_key_benches_the_whole_provider() -> None:
    transport = ScriptedTransport(
        {
            "alpha-large": [Reply(status=401, error_body="Invalid API Key")],
            "beta-coder": [Reply(text="ok")],
        }
    )
    async with routed(transport) as ctx:
        await ctx.router.session("backend").complete(ask("hi"))
        health = await ctx.gateway.state.health(["alpha/alpha-large", "alpha/alpha-small"])
    assert all(h.cooldown_reason == "auth_failed" for h in health.values())


async def test_when_every_model_is_out_the_caller_learns_when_to_come_back() -> None:
    transport = ScriptedTransport(
        {
            "alpha-large": [Reply.daily_quota("2h0m0s")],
            "alpha-small": [Reply.rate_limited(45)],
            "beta-coder": [Reply.rate_limited(90)],
        }
    )
    clock = FakeClock()
    async with routed(transport, clock) as ctx:
        with pytest.raises(AllModelsUnavailable) as info:
            await ctx.router.session("backend").complete(ask("hi"))
    assert info.value.retry_at == pytest.approx(clock.now + 45)
    assert "cooling_down" in str(info.value)


async def test_without_keys_nothing_is_called_and_the_reason_is_clear() -> None:
    transport = ScriptedTransport()
    async with routed(transport, groq_api_key=SecretStr(""), cerebras_api_key=SecretStr("")) as ctx:
        with pytest.raises(AllModelsUnavailable, match="no_key"):
            await ctx.router.session("backend").complete(ask("hi"))
    assert transport.requests == []


async def test_private_data_stays_with_providers_that_do_not_train() -> None:
    transport = ScriptedTransport(
        {
            "alpha-large": [Reply.rate_limited()],
            "alpha-small": [Reply(text="ok")],
            "beta-coder": [Reply(text="should never be asked")],
        }
    )
    async with routed(transport) as ctx:
        session = ctx.router.session("backend", private_data=True)
        result = await session.complete(ask("hi"))
    # beta ranks above alpha-small for coding, but it trains on prompts
    assert result.model_id == "alpha/alpha-small"
    assert transport.calls_to("beta-coder") == 0


async def test_a_reviewer_is_routed_away_from_the_authors_family() -> None:
    transport = ScriptedTransport({"beta-coder": [Reply(text="looks fine")]})
    async with routed(transport) as ctx:
        session = ctx.router.session("reviewer", avoid_families=["fam-a"])
        result = await session.complete(ask("review this diff", tools=False))
    assert result.model_id == "beta/beta-coder"


async def test_quota_is_reserved_so_a_used_up_window_is_skipped_without_a_call() -> None:
    transport = ScriptedTransport(
        {"alpha-large": [Reply(text="ok")], "beta-coder": [Reply(text="b")]}
    )
    async with routed(transport) as ctx:
        session = ctx.router.session("backend")
        for _ in range(30):  # alpha-large allows 30 requests a minute
            await session.complete(ask("hi"))
        result = await session.complete(ask("one more"))
    assert result.model_id == "beta/beta-coder"
    assert transport.calls_to("alpha-large") == 30
    skipped = [d for d in result.decisions if d.event is Event.USE]
    assert skipped[0].after == SkipReason.NO_QUOTA.value

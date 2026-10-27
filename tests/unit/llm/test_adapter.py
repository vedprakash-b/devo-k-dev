from __future__ import annotations

import json

import pytest

from devokdev.llm.adapter import StreamTimeouts, build_payload, to_provider_messages
from devokdev.llm.errors import ErrorKind, ProviderError
from devokdev.llm.messages import (
    CompletionRequest,
    FinishReason,
    Message,
    ToolCall,
    ToolSpec,
)
from devokdev.llm.registry import Quirks
from devokdev.llm.scripted import Reply, ScriptedTransport
from tests.support import endpoint, make_adapter, make_registry

REGISTRY = make_registry()
ALPHA = REGISTRY.model("alpha/alpha-large")
HELLO = CompletionRequest(messages=(Message.system("Be brief."), Message.user("Say hello")))
LIST_DIR = ToolSpec(
    name="list_dir",
    description="List a directory",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}},
)


async def call(transport: ScriptedTransport, request: CompletionRequest = HELLO, **timeouts: float):  # type: ignore[no-untyped-def]
    adapter = make_adapter(transport, StreamTimeouts(**timeouts) if timeouts else None)
    return await adapter.complete(endpoint(REGISTRY, "alpha", "sk-test"), ALPHA, request)


async def test_streams_text_and_reports_usage_and_timing() -> None:
    transport = ScriptedTransport(
        {"alpha-large": [Reply(text="Hello, Ved! Namaste.", usage=(12, 6))]}
    )
    result, _ = await call(transport)
    assert result.message.content == "Hello, Ved! Namaste."
    assert result.finish_reason is FinishReason.STOP
    assert (result.usage.input_tokens, result.usage.output_tokens) == (12, 6)
    assert not result.usage.estimated
    assert result.ttft_ms is not None
    host, payload = transport.requests[0]
    assert host == "alpha.test"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}


async def test_tool_call_fragments_are_assembled_with_canonical_ids() -> None:
    reply = Reply(tool_calls=(("list_dir", {"path": "src/devokdev"}),))
    request = HELLO.model_copy(update={"tools": (LIST_DIR,)})
    result, _ = await call(ScriptedTransport({"alpha-large": [reply]}), request)
    (tool_call,) = result.message.tool_calls
    assert tool_call.name == "list_dir"
    assert tool_call.parsed_arguments() == {"path": "src/devokdev"}
    assert tool_call.id != "provider_0"  # replaced by a canonical ID
    assert result.finish_reason is FinishReason.TOOL_CALLS


async def test_reasoning_is_kept_apart_from_the_answer() -> None:
    reply = Reply(text="4", reasoning="2 plus 2 is 4")
    result, _ = await call(ScriptedTransport({"alpha-large": [reply]}))
    assert result.message.content == "4"
    assert result.reasoning == "2 plus 2 is 4"


async def test_missing_usage_is_estimated_and_marked() -> None:
    result, _ = await call(ScriptedTransport({"alpha-large": [Reply(text="hi", usage=None)]}))
    assert result.usage.estimated
    assert result.usage.input_tokens > 0


async def test_rate_limit_headers_are_returned_with_the_result() -> None:
    reply = Reply(
        text="ok",
        headers={"x-ratelimit-remaining-requests": "41", "x-ratelimit-limit-requests": "1000"},
    )
    _, observation = await call(ScriptedTransport({"alpha-large": [reply]}))
    assert observation.windows[0].remaining == 41


async def test_a_429_becomes_a_rate_limited_error_with_retry_after() -> None:
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [Reply.rate_limited(retry_after_s=17)]}))
    assert info.value.kind is ErrorKind.RATE_LIMITED
    assert info.value.retry_after_s == 17
    assert info.value.model_id == "alpha/alpha-large"


async def test_a_daily_quota_429_is_quota_exhausted() -> None:
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [Reply.daily_quota("2h0m0s")]}))
    assert info.value.kind is ErrorKind.QUOTA_EXHAUSTED
    assert info.value.retry_after_s == pytest.approx(7200)


async def test_no_token_before_the_deadline_is_a_hung_stream() -> None:
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [Reply.hung(5)]}), first_token_s=0.05)
    assert info.value.kind is ErrorKind.HUNG_STREAM


async def test_keep_alive_comments_do_not_count_as_a_first_token() -> None:
    # Reply.hung sends ": keep-alive" immediately, then nothing: still hung.
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [Reply.hung(5)]}), first_token_s=0.05)
    assert "no output within" in info.value.message


async def test_a_dropped_connection_mid_stream_is_a_network_error() -> None:
    reply = Reply(text="a long answer that never finishes", drop_after_chunks=2)
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [reply]}))
    assert info.value.kind is ErrorKind.NETWORK


async def test_an_error_event_inside_a_200_stream_is_classified() -> None:
    reply = Reply(stream_error={"code": 429, "message": "Rate limit exceeded"})
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [reply]}))
    assert info.value.kind is ErrorKind.RATE_LIMITED


async def test_the_api_key_never_appears_in_errors() -> None:
    reply = Reply(status=401, error_body="Invalid API key sk-test provided")
    with pytest.raises(ProviderError) as info:
        await call(ScriptedTransport({"alpha-large": [reply]}))
    assert info.value.kind is ErrorKind.AUTH_FAILED
    assert "sk-test" not in str(info.value)


async def test_list_models_reads_the_models_endpoint() -> None:
    transport = ScriptedTransport(models_by_host={"alpha.test": ["alpha-small", "alpha-large"]})
    adapter = make_adapter(transport)
    assert await adapter.list_models(endpoint(REGISTRY, "alpha")) == ["alpha-large", "alpha-small"]


# ------------------------------------------------------------------ wire format and quirks


def test_system_prompt_can_be_merged_into_the_first_user_turn() -> None:
    quirks = Quirks(system_prompt="merge_into_user")
    wire = to_provider_messages((Message.system("Rules."), Message.user("Hi")), quirks)
    assert wire == [{"role": "user", "content": "Rules.\n\nHi"}]


def test_assistant_tool_turns_follow_the_content_quirk() -> None:
    call_ = ToolCall(name="list_dir", arguments="{}")
    turn = Message.assistant(None, (call_,))
    assert to_provider_messages((turn,), Quirks())[0]["content"] is None
    assert (
        to_provider_messages((turn,), Quirks(assistant_tool_content="empty_string"))[0]["content"]
        == ""
    )


def test_tool_results_carry_the_name_only_when_the_provider_wants_it() -> None:
    call_ = ToolCall(name="list_dir", arguments="{}")
    result = Message.tool_result(call_, "a.py")
    assert "name" not in to_provider_messages((result,), Quirks())[0]
    assert to_provider_messages((result,), Quirks(tool_message_name=True))[0]["name"] == "list_dir"


def test_payload_respects_model_limits_and_json_support() -> None:
    request = HELLO.model_copy(
        update={
            "max_output_tokens": 999_999,
            "json_mode": True,
            "tools": (LIST_DIR,),
            "tool_choice": "auto",
        }
    )
    payload = build_payload(ALPHA, Quirks(max_tokens_field="max_completion_tokens"), request)
    assert payload["max_completion_tokens"] == ALPHA.max_output_tokens
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tools"][0]["function"]["name"] == "list_dir"
    assert payload["tool_choice"] == "auto"
    small = REGISTRY.model("alpha/alpha-small")  # json_mode: false
    assert "response_format" not in build_payload(small, Quirks(), request)
    json.dumps(payload)  # the payload is plain JSON

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from devokdev.llm.messages import (
    TOOL_CALL_ID_PATTERN,
    CompletionRequest,
    Message,
    Role,
    ToolCall,
    ToolSpec,
    new_tool_call_id,
)
from devokdev.llm.tokens import estimate_input_tokens, estimate_text_tokens


def test_tool_call_ids_always_match_the_strictest_provider_format() -> None:
    ids = {new_tool_call_id() for _ in range(200)}
    assert all(re.match(TOOL_CALL_ID_PATTERN, i) for i in ids)
    assert len(ids) == 200  # random enough not to collide in a conversation


def test_provider_style_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ToolCall(id="call_abc-123_xyz", name="read_file")


def test_tool_results_must_answer_a_call() -> None:
    with pytest.raises(ValidationError, match="tool_call_id"):
        Message(role=Role.TOOL, content="42")
    call = ToolCall(name="add", arguments='{"a": 1}')
    result = Message.tool_result(call, "1")
    assert result.tool_call_id == call.id
    assert result.name == "add"


def test_only_assistants_call_tools() -> None:
    with pytest.raises(ValidationError, match="only assistant"):
        Message(role=Role.USER, content="hi", tool_calls=(ToolCall(name="x"),))


def test_parsed_arguments_rejects_non_objects() -> None:
    assert ToolCall(name="f", arguments='{"path": "a.py"}').parsed_arguments() == {"path": "a.py"}
    with pytest.raises(ValueError, match="not a JSON object"):
        ToolCall(name="f", arguments="[1, 2]").parsed_arguments()


def test_requests_are_immutable_and_append_returns_a_copy() -> None:
    request = CompletionRequest(messages=(Message.user("hi"),))
    longer = request.appended(Message.assistant("hello"))
    assert len(request.messages) == 1
    assert len(longer.messages) == 2


def test_token_estimate_is_pessimistic_for_non_latin_text() -> None:
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("abcd") == 1
    # three bytes per Devanagari character: more tokens per character than English
    assert estimate_text_tokens("नमस्ते") > estimate_text_tokens("namaste")


def test_tools_count_towards_input_tokens() -> None:
    plain = CompletionRequest(messages=(Message.user("list files"),))
    tool = ToolSpec(
        name="list_dir",
        description="List the files in a directory",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    with_tools = plain.model_copy(update={"tools": (tool,)})
    assert estimate_input_tokens(with_tools) > estimate_input_tokens(plain)

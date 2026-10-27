"""Devo-K-Dev's canonical conversation format.

Every conversation is stored in these types, never in a provider's format. That is what
makes mid-task handoff possible: when one model fails, the same conversation is converted
for the next provider and replayed (see ``adapter.to_provider_messages``).

Tool-call IDs are generated here, not taken from providers. They are nine letters and
digits, the strictest format any provider accepts (Mistral rejects anything else), so a
conversation started on one provider can always continue on another.
"""

from __future__ import annotations

import json
import secrets
import string
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID_ALPHABET = string.ascii_letters + string.digits
TOOL_CALL_ID_PATTERN = r"^[A-Za-z0-9]{9}$"


def new_tool_call_id() -> str:
    """A fresh canonical tool-call ID: nine random letters and digits."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(9))


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """A model asking to run a tool. ``arguments`` is the raw JSON text the model wrote."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_tool_call_id, pattern=TOOL_CALL_ID_PATTERN)
    name: str = Field(min_length=1)
    arguments: str = "{}"

    def parsed_arguments(self) -> dict[str, Any]:
        """The arguments as a dict. Raises ValueError if they are not a JSON object."""
        value = json.loads(self.arguments or "{}")
        if not isinstance(value, dict):
            raise ValueError(f"arguments of {self.name} are not a JSON object")
        return value


class Message(BaseModel):
    """One turn of a conversation."""

    model_config = ConfigDict(frozen=True)

    role: Role
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    # For role=tool: which call this result answers, and the tool's name.
    tool_call_id: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.tool_calls and self.role is not Role.ASSISTANT:
            raise ValueError("only assistant messages can contain tool calls")
        if self.role is Role.TOOL and not self.tool_call_id:
            raise ValueError("a tool message needs the tool_call_id it answers")
        if self.role is not Role.TOOL and self.tool_call_id:
            raise ValueError("only tool messages carry a tool_call_id")
        return self

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role=Role.SYSTEM, content=text)

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=text)

    @classmethod
    def assistant(cls, text: str | None = None, tool_calls: tuple[ToolCall, ...] = ()) -> Message:
        return cls(role=Role.ASSISTANT, content=text, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, call: ToolCall, content: str) -> Message:
        return cls(role=Role.TOOL, content=content, tool_call_id=call.id, name=call.name)


class ToolSpec(BaseModel):
    """A tool the model may call. ``parameters`` is a JSON Schema object."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})


class CompletionRequest(BaseModel):
    """Everything one model call needs, independent of provider."""

    model_config = ConfigDict(frozen=True)

    messages: tuple[Message, ...] = Field(min_length=1)
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: Literal["auto", "none", "required"] | None = None
    max_output_tokens: int = Field(default=1024, ge=1)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    json_mode: bool = False

    def appended(self, *messages: Message) -> CompletionRequest:
        """A copy with extra messages at the end (requests are immutable)."""
        return self.model_copy(update={"messages": (*self.messages, *messages)})


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    OTHER = "other"


class Usage(BaseModel):
    """Token counts. ``estimated`` is True when the provider did not report usage."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated: bool = False

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class CompletionResult(BaseModel):
    """What one successful model call produced, plus how it went."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    message: Message
    finish_reason: FinishReason
    usage: Usage
    # Hidden reasoning some models stream separately. Kept for traces, never replayed.
    reasoning: str | None = None
    ttft_ms: float | None = None
    duration_ms: float = 0.0

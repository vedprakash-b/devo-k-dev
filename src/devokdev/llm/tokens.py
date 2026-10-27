"""Cheap token estimates, used for budgeting before a call is made.

Exact counts need each model family's tokenizer, which arrives with the context manager
(M2). Until then, a deliberately pessimistic estimate is enough: about four UTF-8 bytes per
token over-counts English slightly and handles non-Latin scripts, which use more bytes per
character. After each call, the provider's reported usage replaces the estimate.
"""

from __future__ import annotations

import json
import math

from devokdev.llm.messages import CompletionRequest, Message

BYTES_PER_TOKEN = 4.0
PER_MESSAGE_OVERHEAD = 4  # role markers and separators every chat template adds
PER_REQUEST_OVERHEAD = 3


def estimate_text_tokens(text: str | None) -> int:
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / BYTES_PER_TOKEN)


def estimate_message_tokens(message: Message) -> int:
    tokens = PER_MESSAGE_OVERHEAD + estimate_text_tokens(message.content)
    for call in message.tool_calls:
        tokens += estimate_text_tokens(call.name) + estimate_text_tokens(call.arguments) + 4
    return tokens


def estimate_input_tokens(request: CompletionRequest) -> int:
    """Tokens the prompt will use: messages plus tool definitions."""
    tokens = PER_REQUEST_OVERHEAD + sum(estimate_message_tokens(m) for m in request.messages)
    if request.tools:
        tools_json = json.dumps([t.model_dump() for t in request.tools], separators=(",", ":"))
        tokens += estimate_text_tokens(tools_json)
    return tokens

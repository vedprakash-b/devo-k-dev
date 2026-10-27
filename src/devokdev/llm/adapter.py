"""The one adapter every provider is reached through: OpenAI-compatible chat over httpx.

Almost every free provider speaks the OpenAI chat-completions API, so one adapter plus a
few per-provider ``Quirks`` covers them all. It talks HTTP directly with httpx rather than
through the openai SDK because the router needs things the SDK hides or does on its own:
raw status codes and error bodies, rate-limit headers on every response, the time to the
first token, and no automatic retries (the router decides whether and where to retry).

Every call streams. Streaming is what makes a hung call detectable: if no token arrives
before ``first_token_s``, the call is abandoned as HUNG_STREAM and the router moves on,
instead of waiting minutes for a server that has silently stalled.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from devokdev.llm.errors import (
    ErrorKind,
    ProviderError,
    classify_http_error,
    classify_stream_error,
    scrub,
)
from devokdev.llm.messages import (
    CompletionRequest,
    CompletionResult,
    FinishReason,
    Message,
    Role,
    ToolCall,
    Usage,
)
from devokdev.llm.ratelimits import RateLimitObservation, parse_rate_limit_headers
from devokdev.llm.registry import ModelSpec, ProviderSpec, Quirks
from devokdev.llm.tokens import estimate_input_tokens, estimate_text_tokens

Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class StreamTimeouts:
    """Deadlines for one call, in seconds."""

    connect_s: float = 10.0
    first_token_s: float = 30.0  # nothing streamed before this: HUNG_STREAM
    stall_s: float = 60.0  # longest silence between two chunks once streaming
    total_s: float = 300.0  # the whole call, first byte to last


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A provider made concrete: URL with placeholders filled in, and its key."""

    provider: ProviderSpec
    base_url: str
    api_key: str


# ------------------------------------------------------------------ request building


def to_provider_messages(messages: tuple[Message, ...], quirks: Quirks) -> list[dict[str, Any]]:
    """Convert canonical messages to the OpenAI wire format, applying a provider's quirks."""
    out: list[dict[str, Any]] = []
    pending_system: list[str] = []
    for message in messages:
        if message.role is Role.SYSTEM:
            if quirks.system_prompt == "merge_into_user":
                pending_system.append(message.content or "")
            else:
                out.append({"role": "system", "content": message.content or ""})
        elif message.role is Role.USER:
            text = message.content or ""
            if pending_system:
                text = "\n\n".join([*pending_system, text])
                pending_system = []
            out.append({"role": "user", "content": text})
        elif message.role is Role.ASSISTANT:
            item: dict[str, Any] = {"role": "assistant"}
            if message.tool_calls:
                empty = "" if quirks.assistant_tool_content == "empty_string" else None
                item["content"] = message.content or empty
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in message.tool_calls
                ]
            else:
                item["content"] = message.content or ""
            out.append(item)
        else:
            tool_item: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": message.tool_call_id,
                "content": message.content or "",
            }
            if quirks.tool_message_name and message.name:
                tool_item["name"] = message.name
            out.append(tool_item)
    if pending_system:  # a system prompt with no user turn after it
        out.append({"role": "user", "content": "\n\n".join(pending_system)})
    return out


def build_payload(model: ModelSpec, quirks: Quirks, request: CompletionRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model.name,
        "messages": to_provider_messages(request.messages, quirks),
        "stream": True,
        quirks.max_tokens_field: min(request.max_output_tokens, model.max_output_tokens),
    }
    if quirks.stream_usage:
        payload["stream_options"] = {"include_usage": True}
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice
    if request.json_mode and model.json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


# ------------------------------------------------------------------ stream parsing


async def iter_sse_data(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Yield the data of each server-sent event. Comments (``: keep-alive``) are skipped.

    OpenRouter sends ``: OPENROUTER PROCESSING`` comments while a model warms up; they
    must not count as the first token, or a hung model would look alive.
    """
    data: list[str] = []
    async for line in lines:
        if not line:
            if data:
                yield "\n".join(data)
                data = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    if data:
        yield "\n".join(data)


@dataclass
class _ToolCallParts:
    name: str = ""
    arguments: list[str] = field(default_factory=list)


@dataclass
class StreamAccumulator:
    """Collects stream chunks into one assistant message."""

    content: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    calls: dict[int, _ToolCallParts] = field(default_factory=dict)
    finish: str | None = None
    usage: dict[str, Any] | None = None

    @property
    def has_activity(self) -> bool:
        """True once the model produced anything: text, a tool call or reasoning.

        Reasoning models think aloud before answering; that thinking proves the call is
        alive, so it counts towards the first-token deadline.
        """
        return bool(self.content) or bool(self.calls) or bool(self.reasoning)

    def feed(self, chunk: dict[str, Any]) -> None:
        usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
        if isinstance(usage, dict):
            self.usage = usage
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or choice.get("message") or {}
            if text := delta.get("content"):
                self.content.append(text)
            if thought := delta.get("reasoning") or delta.get("reasoning_content"):
                self.reasoning.append(thought)
            for position, call in enumerate(delta.get("tool_calls") or []):
                index = call.get("index", position)
                parts = self.calls.setdefault(index, _ToolCallParts())
                function = call.get("function") or {}
                if name := function.get("name"):
                    parts.name = name
                if args := function.get("arguments"):
                    parts.arguments.append(args if isinstance(args, str) else json.dumps(args))
            if reason := choice.get("finish_reason"):
                self.finish = reason

    def message(self) -> Message:
        # Provider tool-call IDs are replaced by canonical ones (see messages.py).
        calls = tuple(
            ToolCall(name=parts.name, arguments="".join(parts.arguments) or "{}")
            for _, parts in sorted(self.calls.items())
            if parts.name
        )
        return Message.assistant("".join(self.content) or None, calls)

    def finish_reason(self) -> FinishReason:
        if self.calls:
            return FinishReason.TOOL_CALLS
        mapping = {
            "stop": FinishReason.STOP,
            "length": FinishReason.LENGTH,
            "tool_calls": FinishReason.TOOL_CALLS,
            "function_call": FinishReason.TOOL_CALLS,
            "content_filter": FinishReason.CONTENT_FILTER,
        }
        return mapping.get(self.finish or "stop", FinishReason.OTHER)


# ------------------------------------------------------------------ the adapter


class OpenAICompatAdapter:
    """Makes one call to one model. Raises ProviderError; never retries on its own."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        timeouts: StreamTimeouts | None = None,
        wall_clock: Clock = time.time,
    ) -> None:
        self._client = client
        self._timeouts = timeouts or StreamTimeouts()
        self._wall_clock = wall_clock

    def _headers(self, endpoint: Endpoint) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {endpoint.api_key}",
            "Accept": "text/event-stream",
            **endpoint.provider.headers,
        }

    async def complete(
        self, endpoint: Endpoint, model: ModelSpec, request: CompletionRequest
    ) -> tuple[CompletionResult, RateLimitObservation]:
        """Stream one completion. Returns the result and the rate-limit headers seen."""
        secrets = (endpoint.api_key,)
        payload = build_payload(model, model.quirks, request)
        t = self._timeouts
        timeout = httpx.Timeout(connect=t.connect_s, read=t.stall_s, write=30.0, pool=t.connect_s)
        loop = asyncio.get_running_loop()
        started = loop.time()
        accumulator = StreamAccumulator()
        ttft_ms: float | None = None
        observation = RateLimitObservation()

        def fail(kind: ErrorKind, message: str) -> ProviderError:
            return ProviderError(kind, message, model_id=model.id, rate_limits=observation)

        try:
            async with asyncio.timeout_at(started + t.first_token_s) as deadline:
                async with self._client.stream(
                    "POST",
                    f"{endpoint.base_url}/chat/completions",
                    json=payload,
                    headers=self._headers(endpoint),
                    timeout=timeout,
                ) as response:
                    observation = parse_rate_limit_headers(
                        response.headers,
                        endpoint.provider.rate_limit_headers.bare_windows,
                        self._wall_clock(),
                    )
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise classify_http_error(
                            response.status_code,
                            body,
                            observation,
                            model_id=model.id,
                            secrets=secrets,
                        )
                    content_type = response.headers.get("content-type", "")
                    if "application/json" in content_type:
                        # A provider that ignored stream=true and answered in one piece.
                        body_json = json.loads(await response.aread())
                        accumulator.feed(body_json)
                        ttft_ms = (loop.time() - started) * 1000
                    else:
                        async for data in iter_sse_data(response.aiter_lines()):
                            if data.strip() == "[DONE]":
                                break
                            chunk = json.loads(data)
                            if "error" in chunk:
                                raise classify_stream_error(
                                    chunk["error"], model_id=model.id, secrets=secrets
                                )
                            accumulator.feed(chunk)
                            if ttft_ms is None and accumulator.has_activity:
                                ttft_ms = (loop.time() - started) * 1000
                                deadline.reschedule(started + t.total_s)
        except ProviderError:
            raise
        except TimeoutError:
            if ttft_ms is None:
                raise fail(
                    ErrorKind.HUNG_STREAM, f"no output within {t.first_token_s:g}s"
                ) from None
            raise fail(ErrorKind.NETWORK, f"call exceeded {t.total_s:g}s") from None
        except httpx.TimeoutException as exc:
            kind = ErrorKind.HUNG_STREAM if ttft_ms is None else ErrorKind.NETWORK
            raise fail(kind, f"{type(exc).__name__}: no data for {t.stall_s:g}s") from None
        except httpx.HTTPError as exc:
            raise fail(ErrorKind.NETWORK, scrub(f"{type(exc).__name__}: {exc}", secrets)) from None
        except json.JSONDecodeError as exc:
            raise fail(ErrorKind.SERVER_ERROR, f"unreadable chunk from provider: {exc}") from None

        message = accumulator.message()
        usage = self._usage(accumulator, request, message)
        result = CompletionResult(
            model_id=model.id,
            message=message,
            finish_reason=accumulator.finish_reason(),
            usage=usage,
            reasoning="".join(accumulator.reasoning) or None,
            ttft_ms=round(ttft_ms, 1) if ttft_ms is not None else None,
            duration_ms=round((loop.time() - started) * 1000, 1),
        )
        return result, observation

    @staticmethod
    def _usage(acc: StreamAccumulator, request: CompletionRequest, message: Message) -> Usage:
        raw = acc.usage or {}
        prompt = raw.get("prompt_tokens")
        completion = raw.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            return Usage(input_tokens=prompt, output_tokens=completion)
        out_text = (message.content or "") + "".join(c.arguments for c in message.tool_calls)
        out_text += "".join(acc.reasoning)
        return Usage(
            input_tokens=estimate_input_tokens(request),
            output_tokens=estimate_text_tokens(out_text),
            estimated=True,
        )

    async def list_models(self, endpoint: Endpoint) -> list[str]:
        """The model IDs a provider currently serves (GET /models)."""
        secrets = (endpoint.api_key,)
        try:
            response = await self._client.get(
                f"{endpoint.base_url}/models",
                headers={"Authorization": f"Bearer {endpoint.api_key}"},
                timeout=httpx.Timeout(20.0),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                ErrorKind.NETWORK, scrub(f"{type(exc).__name__}: {exc}", secrets)
            ) from None
        if response.status_code >= 400:
            raise classify_http_error(
                response.status_code, response.text, RateLimitObservation(), secrets=secrets
            )
        data = response.json().get("data") or []
        return sorted(str(item["id"]) for item in data if isinstance(item, dict) and "id" in item)

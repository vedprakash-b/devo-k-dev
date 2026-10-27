"""A scripted fake provider, for tests, the offline demo, and chaos tests later.

``ScriptedTransport`` plugs into httpx in place of the network. Each model gets a queue of
``Reply`` objects; every call to that model takes the next one. A reply can be a normal
streamed answer, a tool call, an HTTP error with headers (a 429 with ``retry-after``), a
stream that never sends a token, or one that dies half-way. Nothing touches the network,
so the router's failure handling can be tested exactly and without API keys.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class Reply:
    """One scripted response."""

    text: str | None = None
    tool_calls: tuple[tuple[str, dict[str, Any]], ...] = ()
    reasoning: str | None = None
    status: int = 200
    error_body: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    usage: tuple[int, int] | None = (50, 20)
    # Seconds of silence before the first chunk; longer than the deadline means "hung".
    first_chunk_delay_s: float = 0.0
    # Stop the stream after this many content chunks, as if the connection dropped.
    drop_after_chunks: int | None = None
    # Send an error event inside an HTTP 200 stream (OpenRouter style).
    stream_error: dict[str, Any] | None = None
    finish_reason: str | None = None

    @classmethod
    def rate_limited(cls, retry_after_s: float = 30.0, body: str | None = None) -> Reply:
        return cls(
            status=429,
            headers={"retry-after": f"{retry_after_s:g}"},
            error_body=body
            or json.dumps({"error": {"message": "Rate limit reached: requests per minute"}}),
        )

    @classmethod
    def daily_quota(cls, reset_in: str = "6h0m0s") -> Reply:
        return cls(
            status=429,
            headers={
                "x-ratelimit-remaining-requests-day": "0",
                "x-ratelimit-reset-requests-day": reset_in,
            },
            error_body=json.dumps(
                {"error": {"message": "Rate limit reached on requests per day (RPD)"}}
            ),
        )

    @classmethod
    def server_error(cls, status: int = 503) -> Reply:
        return cls(status=status, error_body='{"error": {"message": "overloaded"}}')

    @classmethod
    def hung(cls, seconds: float = 3600.0) -> Reply:
        return cls(text="too late", first_chunk_delay_s=seconds)


class _SSEBody(httpx.AsyncByteStream):
    def __init__(self, reply: Reply, model: str) -> None:
        self._reply = reply
        self._model = model

    def _chunk(self, delta: dict[str, Any], finish: str | None = None) -> bytes:
        body = {
            "id": "chatcmpl-scripted",
            "object": "chat.completion.chunk",
            "model": self._model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body)}\n\n".encode()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        reply = self._reply
        yield b": keep-alive\n\n"
        if reply.first_chunk_delay_s:
            await asyncio.sleep(reply.first_chunk_delay_s)
        if reply.stream_error is not None:
            yield f"data: {json.dumps({'error': reply.stream_error})}\n\n".encode()
            return
        if reply.reasoning:
            yield self._chunk({"reasoning": reply.reasoning})
        pieces = _split(reply.text or "")
        for count, piece in enumerate(pieces, start=1):
            yield self._chunk({"content": piece})
            if reply.drop_after_chunks is not None and count >= reply.drop_after_chunks:
                raise httpx.ReadError("connection reset by peer")
        for index, (name, args) in enumerate(reply.tool_calls):
            text_args = json.dumps(args)
            half = len(text_args) // 2
            first = {"index": index, "id": f"provider_{index}", "type": "function"}
            yield self._chunk(
                {
                    "tool_calls": [
                        {**first, "function": {"name": name, "arguments": text_args[:half]}}
                    ]
                }
            )
            yield self._chunk(
                {"tool_calls": [{"index": index, "function": {"arguments": text_args[half:]}}]}
            )
        finish = reply.finish_reason or ("tool_calls" if reply.tool_calls else "stop")
        yield self._chunk({}, finish)
        if reply.usage is not None:
            usage = {"prompt_tokens": reply.usage[0], "completion_tokens": reply.usage[1]}
            yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n".encode()
        yield b"data: [DONE]\n\n"


def _split(text: str, size: int = 8) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)] if text else []


class ScriptedTransport(httpx.AsyncBaseTransport):
    """Answers chat calls from per-model reply queues and records every request.

    Scripts are keyed by the model name sent on the wire, or by ``host/model`` when two
    providers serve a model with the same name. When a queue runs dry, the last reply
    repeats, so a script of one reply means "always answer like this".
    """

    def __init__(
        self,
        scripts: dict[str, Iterable[Reply]] | None = None,
        models_by_host: dict[str, list[str]] | None = None,
    ) -> None:
        self._queues: dict[str, deque[Reply]] = {k: deque(v) for k, v in (scripts or {}).items()}
        self._last: dict[str, Reply] = {}
        self._models_by_host = models_by_host or {}
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def add(self, key: str, *replies: Reply) -> None:
        self._queues.setdefault(key, deque()).extend(replies)

    def calls_to(self, model: str) -> int:
        return sum(1 for _, payload in self.requests if payload.get("model") == model)

    def _next(self, host: str, model: str) -> Reply:
        for key in (f"{host}/{model}", model):
            queue = self._queues.get(key)
            if queue:
                reply = queue.popleft()
                self._last[key] = reply
                return reply
            if key in self._last:
                return self._last[key]
        return Reply(text=f"(no script for {model})")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if request.method == "GET" and request.url.path.endswith("/models"):
            data = [{"id": m, "object": "model"} for m in self._models_by_host.get(host, [])]
            return httpx.Response(200, json={"object": "list", "data": data})
        payload = json.loads(request.content or b"{}")
        model = str(payload.get("model", ""))
        self.requests.append((host, payload))
        reply = self._next(host, model)
        if reply.status >= 400:
            return httpx.Response(
                reply.status, headers=reply.headers, content=(reply.error_body or "").encode()
            )
        headers = {"content-type": "text/event-stream", **reply.headers}
        return httpx.Response(200, headers=headers, stream=_SSEBody(reply, model))


class InjectFaults(httpx.AsyncBaseTransport):
    """Fail the first ``times`` chat calls with a scripted reply, then use the real network.

    Used by ``devokdev models chat --simulate-429`` to show a live fallback on demand, and
    by chaos tests later. Model listings are never faulted.
    """

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        reply: Reply | None = None,
        times: int = 1,
    ) -> None:
        self._inner = inner
        self._reply = reply or Reply.rate_limited(30)
        self._remaining = times
        self.injected: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._remaining > 0 and request.method == "POST":
            self._remaining -= 1
            payload = json.loads(request.content or b"{}")
            self.injected.append(str(payload.get("model", "")))
            reply = self._reply
            return httpx.Response(
                reply.status, headers=reply.headers, content=(reply.error_body or "").encode()
            )
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()

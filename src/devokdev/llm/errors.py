"""Every way a model call can fail, as one exception with a ``kind``.

The router does not care about HTTP codes; it cares about what to do next. So the adapter
classifies each failure into a kind, and the router has one rule per kind (see
``router.actions``). The failure table in ``docs/learning/M1.md`` ("Failure → How it is
detected → What the router does") is implemented by ``classify_http_error`` here and
``action_for`` there.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum

from devokdev.llm.ratelimits import RateLimitObservation


class ErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"  # 429 for a short window: wait a little, use another model
    QUOTA_EXHAUSTED = "quota_exhausted"  # daily quota, credits or access gone: wait for reset
    AUTH_FAILED = "auth_failed"  # 401: the key is wrong; no point retrying this provider
    MODEL_UNAVAILABLE = "model_unavailable"  # 404: model renamed or withdrawn
    CONTEXT_TOO_LONG = "context_too_long"  # the conversation does not fit this model
    BAD_REQUEST = "bad_request"  # 400 for another reason, often a provider quirk
    SERVER_ERROR = "server_error"  # 5xx or overloaded
    NETWORK = "network_error"  # connection failed, dropped or too slow mid-stream
    HUNG_STREAM = "hung_stream"  # no first token before the deadline
    INVALID_OUTPUT = "invalid_output"  # answered, but not in a usable shape


class ProviderError(Exception):
    """A failed model call, already classified. Messages are trimmed and key-free."""

    def __init__(
        self,
        kind: ErrorKind,
        message: str,
        *,
        model_id: str | None = None,
        status: int | None = None,
        retry_after_s: float | None = None,
        rate_limits: RateLimitObservation | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.model_id = model_id
        self.status = status
        self.retry_after_s = retry_after_s
        self.rate_limits = rate_limits

    def __str__(self) -> str:
        where = f" [{self.model_id}]" if self.model_id else ""
        code = f" HTTP {self.status}" if self.status else ""
        return f"{self.kind.value}{code}{where}: {self.message}"


# A daily or monthly limit, in the words providers use: Groq "(RPD)", OpenRouter
# "free-models-per-day", Gemini "PerDay", Cloudflare "daily free allocation".
_LONG_WINDOW = re.compile(r"per[\s_-]?day|daily|\b(rpd|tpd)\b|per[\s_-]?month|monthly", re.I)
_CONTEXT = re.compile(
    r"context[\s_]length|context[\s_]window|maximum context|too many tokens|"
    r"prompt is too long|reduce the length|input is too long|exceeds? the (?:maximum|context)",
    re.I,
)
# "Please try again in 7.66s" (Groq), "retry in 32.5s", '"retryDelay": "32s"' (Gemini)
_RETRY_HINT = re.compile(
    r"(?:try again in|retry in|retrydelay\"?:\s*\"?)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|s)?",
    re.I,
)
MAX_MESSAGE_CHARS = 500


def retry_hint_from_text(text: str) -> float | None:
    match = _RETRY_HINT.search(text)
    if match is None:
        return None
    value = float(match["value"])
    return value / 1000.0 if match["unit"] == "ms" else value


def error_text(body: str) -> str:
    """The human message inside a JSON error body, or the body itself.

    Providers wrap errors as {"error": {"message": ...}}, {"error": "..."} or
    [{"error": {...}}] (Gemini). Classification still reads the whole body, because
    details such as Gemini's quota ID ("PerDay") live outside the message.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        error = data.get("error", data)
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])
        if isinstance(error, str):
            return error
    return body


def scrub(text: str, secrets: tuple[str, ...]) -> str:
    """Trim an error body and remove any secret it might echo back."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = " ".join(text.split())
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[: MAX_MESSAGE_CHARS - 1] + "…"
    return text


def classify_http_error(
    status: int,
    body: str,
    rate_limits: RateLimitObservation,
    *,
    model_id: str | None = None,
    secrets: tuple[str, ...] = (),
) -> ProviderError:
    """Turn an HTTP error response into a ProviderError the router can act on."""
    message = scrub(error_text(body), secrets) or f"HTTP {status}"
    retry_after = rate_limits.retry_after_s or retry_hint_from_text(body)

    kind: ErrorKind
    if status == 429:
        long_window = bool(_LONG_WINDOW.search(body)) or bool(rate_limits.exhausted_long_windows())
        kind = ErrorKind.QUOTA_EXHAUSTED if long_window else ErrorKind.RATE_LIMITED
        if kind is ErrorKind.QUOTA_EXHAUSTED:
            resets = [
                w.reset_after_s
                for w in rate_limits.exhausted_long_windows()
                if w.reset_after_s is not None
            ]
            retry_after = max(resets) if resets else retry_after
    elif status in (402, 403):
        kind = ErrorKind.QUOTA_EXHAUSTED
    elif status == 401:
        kind = ErrorKind.AUTH_FAILED
    elif status == 404:
        kind = ErrorKind.MODEL_UNAVAILABLE
    elif status == 413 or (status in (400, 422) and _CONTEXT.search(body)):
        kind = ErrorKind.CONTEXT_TOO_LONG
    elif status == 408:
        kind = ErrorKind.NETWORK
    elif status >= 500:
        kind = ErrorKind.SERVER_ERROR
    else:
        kind = ErrorKind.BAD_REQUEST
    return ProviderError(
        kind,
        message,
        model_id=model_id,
        status=status,
        retry_after_s=retry_after,
        rate_limits=rate_limits,
    )


def classify_stream_error(
    error: object, *, model_id: str | None = None, secrets: tuple[str, ...] = ()
) -> ProviderError:
    """An error that arrives inside the stream, after HTTP 200 (OpenRouter does this).

    The error object usually carries the HTTP-style code it would have had.
    """
    code: int | None = None
    text = str(error)
    if isinstance(error, dict):
        raw_code = error.get("code")
        if isinstance(raw_code, int):
            code = raw_code
        elif isinstance(raw_code, str) and raw_code.isdigit():
            code = int(raw_code)
        text = str(error.get("message") or error)
    if code is not None and code >= 400:
        return classify_http_error(
            code, text, RateLimitObservation(), model_id=model_id, secrets=secrets
        )
    return ProviderError(
        ErrorKind.SERVER_ERROR, scrub(text, secrets) or "error in stream", model_id=model_id
    )

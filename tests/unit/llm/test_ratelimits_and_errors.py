from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from devokdev.llm.errors import (
    ErrorKind,
    classify_http_error,
    classify_stream_error,
    retry_hint_from_text,
)
from devokdev.llm.ratelimits import (
    Dimension,
    RateLimitObservation,
    Window,
    WindowObservation,
    parse_duration,
    parse_rate_limit_headers,
)

NOW = 1_800_000_000.0
GROQ_WINDOWS = {Dimension.REQUESTS: Window.DAY, Dimension.TOKENS: Window.MINUTE}


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("2m59.56s", 179.56),
        ("7.66s", 7.66),
        ("1h0m0s", 3600.0),
        ("500ms", 0.5),
        ("59.5", 59.5),
        (str(int((NOW + 30) * 1000)), 30.0),  # epoch milliseconds (OpenRouter)
        (str(int(NOW + 90)), 90.0),  # epoch seconds
    ],
)
def test_parse_duration_reads_every_provider_format(text: str, seconds: float) -> None:
    assert parse_duration(text, NOW) == pytest.approx(seconds)


@pytest.mark.parametrize("text", ["", "soon", "12 parsecs", "1m30x"])
def test_parse_duration_returns_none_for_nonsense(text: str) -> None:
    assert parse_duration(text, NOW) is None


@given(st.text(max_size=30))
def test_parse_duration_never_raises_or_goes_negative(text: str) -> None:
    value = parse_duration(text, NOW)
    assert value is None or value >= 0


def test_groq_style_bare_headers_use_the_configured_windows() -> None:
    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": "998",
        "x-ratelimit-reset-requests": "2m52.8s",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "7400",
        "x-ratelimit-reset-tokens": "4.5s",
        "content-type": "text/event-stream",
    }
    obs = parse_rate_limit_headers(headers, GROQ_WINDOWS, NOW)
    by_key = {(w.dimension, w.window): w for w in obs.windows}
    daily = by_key[(Dimension.REQUESTS, Window.DAY)]
    assert (daily.limit, daily.remaining) == (1000, 998)
    assert daily.reset_after_s == pytest.approx(172.8)
    assert by_key[(Dimension.TOKENS, Window.MINUTE)].remaining == 7400


def test_cerebras_style_suffixed_headers_need_no_configuration() -> None:
    headers = {
        "x-ratelimit-limit-tokens-minute": "30000",
        "x-ratelimit-remaining-tokens-minute": "29500",
        "x-ratelimit-remaining-requests-day": "0",
        "x-ratelimit-reset-requests-day": "3600.5",
    }
    obs = parse_rate_limit_headers(headers, {}, NOW)
    assert [w.window for w in obs.exhausted_long_windows()] == [Window.DAY]


def test_openrouter_headers_without_dimension_count_as_requests() -> None:
    headers = {
        "X-RateLimit-Limit": "20",
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": str(int((NOW + 12) * 1000)),
        "Retry-After": "12",
    }
    obs = parse_rate_limit_headers(headers, {Dimension.REQUESTS: Window.MINUTE}, NOW)
    assert obs.retry_after_s == 12
    assert obs.windows[0].dimension is Dimension.REQUESTS
    assert obs.windows[0].reset_after_s == pytest.approx(12)


def test_unknown_bare_headers_are_ignored_rather_than_guessed() -> None:
    obs = parse_rate_limit_headers({"x-ratelimit-remaining-tokens": "5"}, {}, NOW)
    assert obs.empty


# ------------------------------------------------------------------ classification


def classify(status: int, body: str, obs: RateLimitObservation | None = None) -> ErrorKind:
    return classify_http_error(status, body, obs or RateLimitObservation()).kind


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (
            429,
            "Rate limit reached on tokens per minute (TPM). Please try again in 7.66s",
            ErrorKind.RATE_LIMITED,
        ),
        (
            429,
            "Rate limit reached on requests per day (RPD): Limit 1000",
            ErrorKind.QUOTA_EXHAUSTED,
        ),
        (429, "Rate limit exceeded: free-models-per-day", ErrorKind.QUOTA_EXHAUSTED),
        (
            429,
            "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            ErrorKind.QUOTA_EXHAUSTED,
        ),
        (
            429,
            "you have used up your daily free allocation of 10,000 neurons",
            ErrorKind.QUOTA_EXHAUSTED,
        ),
        (402, "Insufficient credits", ErrorKind.QUOTA_EXHAUSTED),
        (403, "Access denied", ErrorKind.QUOTA_EXHAUSTED),
        (401, "Invalid API Key", ErrorKind.AUTH_FAILED),
        (404, "The model `x` does not exist", ErrorKind.MODEL_UNAVAILABLE),
        (400, "This model's maximum context length is 65536 tokens", ErrorKind.CONTEXT_TOO_LONG),
        (413, "Request too large", ErrorKind.CONTEXT_TOO_LONG),
        (400, "property 'name' is unsupported", ErrorKind.BAD_REQUEST),
        (503, "overloaded", ErrorKind.SERVER_ERROR),
        (500, "internal error", ErrorKind.SERVER_ERROR),
    ],
)
def test_http_errors_map_to_the_router_action_they_need(
    status: int, body: str, kind: ErrorKind
) -> None:
    assert classify(status, body) is kind


def test_a_429_with_an_empty_daily_window_is_quota_exhausted_until_reset() -> None:
    obs = RateLimitObservation(
        windows=(WindowObservation(Dimension.REQUESTS, Window.DAY, 1000, 0, 5400.0),),
        retry_after_s=2.0,
    )
    error = classify_http_error(429, "slow down", obs)
    assert error.kind is ErrorKind.QUOTA_EXHAUSTED
    assert error.retry_after_s == 5400.0  # the daily reset, not the 2 s hint


def test_retry_hints_are_read_from_the_body_when_headers_have_none() -> None:
    assert retry_hint_from_text("Please try again in 7.66s.") == pytest.approx(7.66)
    assert retry_hint_from_text('"retryDelay": "32s"') == 32
    assert retry_hint_from_text("retry in 250ms") == pytest.approx(0.25)
    assert (
        classify_http_error(429, "Please try again in 3s", RateLimitObservation()).retry_after_s
        == 3
    )


def test_error_messages_never_contain_the_key_and_are_trimmed() -> None:
    error = classify_http_error(
        401, "bad key sk-SECRET " + "x" * 2000, RateLimitObservation(), secrets=("sk-SECRET",)
    )
    assert "sk-SECRET" not in str(error)
    assert len(error.message) <= 500


def test_errors_inside_a_stream_are_classified_by_their_code() -> None:
    assert (
        classify_stream_error({"code": 429, "message": "Rate limit exceeded"}).kind
        is ErrorKind.RATE_LIMITED
    )
    assert (
        classify_stream_error({"code": "502", "message": "upstream"}).kind is ErrorKind.SERVER_ERROR
    )
    assert classify_stream_error("something odd").kind is ErrorKind.SERVER_ERROR

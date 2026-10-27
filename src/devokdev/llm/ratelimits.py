"""Reading the rate-limit headers providers send back.

Providers report quota in response headers, but each in its own dialect:

- Groq: ``x-ratelimit-remaining-requests`` (a per-day count) and
  ``x-ratelimit-remaining-tokens`` (per minute), resets as durations like ``2m59.56s``.
- Cerebras: the window is in the name, ``x-ratelimit-remaining-tokens-minute``.
- OpenRouter: ``X-RateLimit-Remaining`` with ``X-RateLimit-Reset`` in epoch milliseconds,
  sent only on a 429.

This module turns all of them into one ``RateLimitObservation``. Which window a header
without a suffix means is provider configuration (``bare_windows``), not guesswork.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from enum import StrEnum


class Dimension(StrEnum):
    REQUESTS = "requests"
    TOKENS = "tokens"


class Window(StrEnum):
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"


WINDOW_SECONDS: dict[Window, float] = {
    Window.MINUTE: 60.0,
    Window.HOUR: 3600.0,
    Window.DAY: 86400.0,
    Window.MONTH: 30 * 86400.0,
}

_HEADER = re.compile(
    r"^x-ratelimit-(?P<field>limit|remaining|reset)"
    r"(?:-(?P<dim>requests|tokens|req|tok))?"
    r"(?:-(?P<win>minute|hour|day|month))?$"
)
_DURATION_PART = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>ms|h|m|s)")
_DIMENSIONS = {"requests": Dimension.REQUESTS, "req": Dimension.REQUESTS}
_DIMENSIONS |= {"tokens": Dimension.TOKENS, "tok": Dimension.TOKENS}


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """What a provider said about one quota window."""

    dimension: Dimension
    window: Window
    limit: int | None = None
    remaining: int | None = None
    reset_after_s: float | None = None


@dataclass(frozen=True, slots=True)
class RateLimitObservation:
    windows: tuple[WindowObservation, ...] = ()
    retry_after_s: float | None = None

    @property
    def empty(self) -> bool:
        return not self.windows and self.retry_after_s is None

    def exhausted_long_windows(self) -> list[WindowObservation]:
        """Day or month windows with nothing left: a daily quota is used up."""
        return [
            w for w in self.windows if w.remaining == 0 and w.window in (Window.DAY, Window.MONTH)
        ]


def parse_duration(value: str, now: float) -> float | None:
    """Seconds until a reset, from any format providers use.

    Accepts durations (``2m59.56s``, ``7.66s``, ``1h0m0s``, ``500ms``), plain seconds
    (``59.5``), epoch timestamps in seconds or milliseconds, and HTTP dates.
    Returns None for anything unreadable. Never negative.
    """
    text = value.strip().lower()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        if number > 1e12:  # epoch milliseconds
            return max(0.0, number / 1000.0 - now)
        if number > 1e9:  # epoch seconds
            return max(0.0, number - now)
        return max(0.0, number)
    parts = list(_DURATION_PART.finditer(text))
    if parts and "".join(p.group(0) for p in parts) == text:
        scale = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
        return sum(float(p["value"]) * scale[p["unit"]] for p in parts)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - now)
    except (TypeError, ValueError, IndexError):
        return None


def _to_int(value: str) -> int | None:
    try:
        return max(0, int(float(value.strip())))
    except ValueError:
        return None


@dataclass
class _Partial:
    limit: int | None = None
    remaining: int | None = None
    reset_after_s: float | None = None
    touched: bool = field(default=False)


def parse_rate_limit_headers(
    headers: Mapping[str, str],
    bare_windows: Mapping[Dimension, Window],
    now: float,
) -> RateLimitObservation:
    """Collect every recognised rate-limit header into one observation.

    ``bare_windows`` says which window a header without a ``-minute``/``-day`` suffix
    refers to, per dimension. A header with no dimension at all (OpenRouter's
    ``X-RateLimit-Remaining``) counts as requests.
    """
    partials: dict[tuple[Dimension, Window], _Partial] = {}
    retry_after: float | None = None
    for raw_name, value in headers.items():
        name = raw_name.lower()
        if name == "retry-after":
            retry_after = parse_duration(value, now)
            continue
        match = _HEADER.match(name)
        if match is None:
            continue
        dimension = _DIMENSIONS.get(match["dim"] or "requests", Dimension.REQUESTS)
        window_name = match["win"]
        window = Window(window_name) if window_name else bare_windows.get(dimension)
        if window is None:
            continue
        partial = partials.setdefault((dimension, window), _Partial())
        partial.touched = True
        if match["field"] == "limit":
            partial.limit = _to_int(value)
        elif match["field"] == "remaining":
            partial.remaining = _to_int(value)
        else:
            partial.reset_after_s = parse_duration(value, now)
    windows = tuple(
        WindowObservation(dim, win, p.limit, p.remaining, p.reset_after_s)
        for (dim, win), p in sorted(partials.items())
        if p.touched
    )
    return RateLimitObservation(windows=windows, retry_after_s=retry_after)

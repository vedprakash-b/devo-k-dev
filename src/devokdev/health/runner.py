"""Run health checks concurrently, each under its own timeout.

A check is a name plus an async probe. The runner never lets one slow or broken
probe stop the others: a timeout or an exception becomes a FAIL result with a
readable reason. This is the same rule the whole project follows later on:
failures are data to report, not crashes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum


class Status(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a probe reports when it finishes on its own."""

    status: Status
    detail: str


Probe = Callable[[], Awaitable[Outcome]]


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    probe: Probe
    # A check that is not required can only ever produce OK or WARN.
    required: bool = True


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: Status
    detail: str
    duration_ms: float


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each secret with '***'. Empty secrets are ignored."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


async def _run_one(check: HealthCheck, timeout_s: float, secrets: Sequence[str]) -> CheckResult:
    started = time.perf_counter()
    try:
        outcome = await asyncio.wait_for(check.probe(), timeout=timeout_s)
        status, detail = outcome.status, outcome.detail
    except TimeoutError:
        status, detail = Status.FAIL, f"timed out after {timeout_s:g}s"
    except Exception as exc:  # a probe must never crash the doctor
        message = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
        status = Status.FAIL
        detail = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    if not check.required and status is Status.FAIL:
        status = Status.WARN
    elapsed_ms = (time.perf_counter() - started) * 1000
    return CheckResult(check.name, status, redact(detail, secrets), round(elapsed_ms, 1))


async def run_checks(
    checks: Sequence[HealthCheck],
    timeout_s: float = 5.0,
    secrets: Sequence[str] = (),
) -> list[CheckResult]:
    """Run all checks at once and return results in the order the checks were given."""
    return list(await asyncio.gather(*(_run_one(c, timeout_s, secrets) for c in checks)))


def exit_code(results: Iterable[CheckResult]) -> int:
    """0 when nothing failed, 1 otherwise. Warnings do not fail the doctor."""
    return 1 if any(r.status is Status.FAIL for r in results) else 0

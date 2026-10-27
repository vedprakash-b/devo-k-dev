from __future__ import annotations

import asyncio

from hypothesis import given
from hypothesis import strategies as st

from devokdev.health.runner import (
    CheckResult,
    HealthCheck,
    Outcome,
    Status,
    exit_code,
    redact,
    run_checks,
)


async def ok() -> Outcome:
    return Outcome(Status.OK, "fine")


async def warn() -> Outcome:
    return Outcome(Status.WARN, "meh")


async def slow() -> Outcome:
    await asyncio.sleep(10)
    return Outcome(Status.OK, "never reached")


async def boom() -> Outcome:
    raise ConnectionRefusedError("connection refused to secret-pw@db")


async def test_results_keep_the_order_checks_were_given() -> None:
    checks = [HealthCheck("a", ok), HealthCheck("b", warn), HealthCheck("c", ok)]
    results = await run_checks(checks)
    assert [r.name for r in results] == ["a", "b", "c"]
    assert [r.status for r in results] == [Status.OK, Status.WARN, Status.OK]


async def test_a_slow_probe_times_out_without_blocking_the_others() -> None:
    results = await run_checks([HealthCheck("slow", slow), HealthCheck("fast", ok)], timeout_s=0.1)
    assert results[0].status is Status.FAIL
    assert "timed out after 0.1s" in results[0].detail
    assert results[1].status is Status.OK
    assert results[0].duration_ms < 5000


async def test_an_exception_becomes_a_fail_with_a_redacted_reason() -> None:
    results = await run_checks([HealthCheck("db", boom)], secrets=["secret-pw"])
    assert results[0].status is Status.FAIL
    assert results[0].detail == "ConnectionRefusedError: connection refused to ***@db"


async def test_an_optional_check_downgrades_fail_to_warn() -> None:
    results = await run_checks([HealthCheck("keys", boom, required=False)])
    assert results[0].status is Status.WARN


def test_exit_code_fails_only_on_fail() -> None:
    def result(status: Status) -> CheckResult:
        return CheckResult("x", status, "", 1.0)

    assert exit_code([result(Status.OK), result(Status.WARN)]) == 0
    assert exit_code([result(Status.OK), result(Status.FAIL)]) == 1
    assert exit_code([]) == 0


def test_redact_ignores_empty_secrets() -> None:
    assert redact("nothing to hide", ["", ""]) == "nothing to hide"


@given(
    prefix=st.text(),
    suffix=st.text(),
    secret=st.text(min_size=4).filter(lambda s: "*" not in s),
)
def test_redact_removes_every_copy_of_a_secret(prefix: str, suffix: str, secret: str) -> None:
    text = f"{prefix}{secret}{suffix}{secret}"
    assert secret not in redact(text, [secret])

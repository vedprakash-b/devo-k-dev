from __future__ import annotations

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from devokdev import __version__, cli
from devokdev.config import Settings
from devokdev.health.runner import HealthCheck, Outcome, Status

runner = CliRunner()


def test_version_prints_the_package_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def _fake_checks(status: Status) -> list[HealthCheck]:
    async def probe() -> Outcome:
        return Outcome(status, "fake detail")

    return [HealthCheck("Fake", probe)]


def test_doctor_exits_zero_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "default_checks", lambda _s: _fake_checks(Status.OK))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "All required checks passed" in result.stdout


def test_doctor_exits_one_when_a_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "default_checks", lambda _s: _fake_checks(Status.FAIL))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "Some checks failed" in result.stdout


def test_doctor_never_prints_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "pw-should-not-print"

    async def leaky() -> Outcome:
        raise RuntimeError(f"auth failed for password {secret}")

    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: Settings(_env_file=None, postgres_password=SecretStr(secret)),
    )
    monkeypatch.setattr(cli, "default_checks", lambda _s: [HealthCheck("Leaky", leaky)])
    result = runner.invoke(cli.app, ["doctor"])
    assert secret not in result.stdout
    assert "***" in result.stdout

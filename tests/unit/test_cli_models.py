"""`devokdev models ...` end to end through Typer, with no keys and no Redis."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from devokdev import cli
from devokdev.config import Settings
from devokdev.health.probes import make_registry_check
from devokdev.health.runner import Status
from devokdev.llm.scripted import Reply, ScriptedTransport
from tests.support import TEST_REGISTRY_YAML

runner = CliRunner()


@pytest.fixture(autouse=True)
def no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 1 refuses at once, so commands fall back to in-memory state quickly.
    monkeypatch.setenv("DEVOKDEV_REDIS_URL", "redis://127.0.0.1:1/0")


def test_demo_shows_a_429_handing_the_conversation_over() -> None:
    result = runner.invoke(cli.app, ["models", "demo"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "rate_limited → switched to" in result.output
    assert "cooldown over → switched back to" in result.output
    assert "staying on" in result.output


def test_list_shows_every_model_and_how_many_are_usable() -> None:
    result = runner.invoke(cli.app, ["models", "list"], env={"COLUMNS": "250"})
    assert result.exit_code == 0, result.output
    assert "groq/openai/gpt-oss-120b" in result.output
    assert "0 of" in result.output
    assert "state: memory (Redis not reachable" in result.output


def test_list_for_a_role_explains_every_exclusion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    models = tmp_path / "models.yaml"
    models.write_text(TEST_REGISTRY_YAML)
    monkeypatch.setenv("DEVOKDEV_MODELS_FILE", str(models))
    monkeypatch.setenv("DEVOKDEV_GROQ_API_KEY", "alpha-key")
    result = runner.invoke(
        cli.app, ["models", "list", "--role", "reviewer"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 0, result.output
    assert "alpha/alpha-large" in result.output
    assert "no_key set cerebras_api_key in .env" in result.output


def test_an_unknown_role_is_an_error_not_a_traceback() -> None:
    result = runner.invoke(cli.app, ["models", "list", "--role", "chef"])
    assert result.exit_code == 1
    assert "unknown role" in result.output


def test_chat_without_keys_explains_what_to_do() -> None:
    result = runner.invoke(cli.app, ["models", "chat", "hello"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "no model available" in result.output
    assert "devokdev models demo" in result.output


def test_profile_without_keys_points_to_the_guide() -> None:
    result = runner.invoke(cli.app, ["models", "profile"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "Getting free keys" in result.output


def test_a_broken_registry_file_is_reported_clearly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    models = tmp_path / "models.yaml"
    models.write_text("version: 1\nroles: {}\nproviders: {x: {base_url: http://insecure}}\n")
    monkeypatch.setenv("DEVOKDEV_MODELS_FILE", str(models))
    result = runner.invoke(cli.app, ["models", "list"], env={"COLUMNS": "200"})
    assert result.exit_code == 1
    assert "is invalid" in result.output


async def test_doctor_checks_the_registry(tmp_path: Path) -> None:
    models = tmp_path / "models.yaml"
    models.write_text(TEST_REGISTRY_YAML)
    settings = Settings(_env_file=None, models_file=models)
    outcome = await make_registry_check(settings).probe()
    assert outcome.status is Status.WARN
    assert "3 models, 0 usable" in outcome.detail


@pytest.fixture
def scripted_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> ScriptedTransport:
    """Point the CLI at the test registry with keys, and replace the network with scripts."""
    models = tmp_path / "models.yaml"
    models.write_text(TEST_REGISTRY_YAML)
    monkeypatch.setenv("DEVOKDEV_MODELS_FILE", str(models))
    monkeypatch.setenv("DEVOKDEV_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEVOKDEV_GROQ_API_KEY", "alpha-key")
    monkeypatch.setenv("DEVOKDEV_CEREBRAS_API_KEY", "beta-key")
    transport = ScriptedTransport()
    real_client = httpx.AsyncClient

    def client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = kwargs.get("transport") or transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("devokdev.router.factory.httpx.AsyncClient", client)
    monkeypatch.setattr("devokdev.cli_models.httpx.AsyncHTTPTransport", lambda: transport)
    return transport


def test_chat_with_a_simulated_429_shows_the_fallback(scripted_network: ScriptedTransport) -> None:
    scripted_network.add("beta-coder", Reply(text="Namaste from beta"))
    result = runner.invoke(
        cli.app, ["models", "chat", "hi", "--role", "backend", "--simulate-429"],
        env={"COLUMNS": "200"},
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "Namaste from beta" in result.output
    assert "rate_limited → switched to beta/beta-coder" in result.output
    assert scripted_network.calls_to("alpha-large") == 0  # the 429 was injected, not sent


def test_profile_prints_a_table_and_caches_the_result(
    scripted_network: ScriptedTransport, tmp_path: Path
) -> None:
    scripted_network.add(
        "beta-coder",
        Reply(text="ALPHA\nseven\nOMEGA"),
        Reply(text='{"name": "Asha", "languages": ["a", "b", "c"], "years_experience": 2}'),
        Reply(tool_calls=(("get_weather", {"city": "Bengaluru", "unit": "celsius"}),)),
        Reply(text="KESAR-4207"),
        Reply(text="KESAR-4320"),
    )
    args = ["models", "profile", "beta/beta-coder", "--no-sandbox"]
    result = runner.invoke(cli.app, args, env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert "Fitness profiles" in result.output
    assert (tmp_path / "data" / "fitness" / "beta_beta-coder.json").is_file()
    again = runner.invoke(cli.app, args, env={"COLUMNS": "200"})
    assert "cached profile is fresh" in again.output

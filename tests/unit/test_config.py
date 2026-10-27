from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from devokdev.config import Settings


def make_settings(**overrides: Any) -> Settings:
    # _env_file=None keeps a developer's real .env out of unit tests
    return Settings(_env_file=None, **overrides)


def test_defaults_point_at_the_local_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEVOKDEV_REDIS_URL", raising=False)
    monkeypatch.delenv("DEVOKDEV_ENV", raising=False)
    settings = make_settings()
    assert settings.redis_url == "redis://127.0.0.1:6379/0"
    assert settings.temporal_address == "127.0.0.1:7233"
    assert settings.env == "dev"


def test_environment_variables_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVOKDEV_POSTGRES_PORT", "5433")
    monkeypatch.setenv("DEVOKDEV_LOG_FORMAT", "json")
    settings = make_settings()
    assert settings.postgres_port == 5433
    assert settings.log_format == "json"


def test_secrets_never_appear_in_repr() -> None:
    settings = make_settings(postgres_password=SecretStr("hunter2-local"))
    assert "hunter2-local" not in repr(settings)
    assert "hunter2-local" not in str(settings.model_dump())


def test_conninfo_quotes_awkward_passwords() -> None:
    settings = make_settings(postgres_password=SecretStr("it's a p@ss word"))
    conninfo = settings.postgres_conninfo()
    assert "password='it\\'s a p@ss word'" in conninfo
    assert "dbname=devokdev" in conninfo


def test_configured_providers_lists_names_not_values() -> None:
    settings = make_settings(
        groq_api_key=SecretStr("gsk_example"),
        cerebras_api_key=SecretStr("   "),
        cloudflare_api_token=SecretStr("cf_example"),
    )
    assert settings.configured_providers() == ["groq", "cloudflare"]


def test_secret_values_collects_only_non_empty_secrets() -> None:
    settings = make_settings(
        postgres_password=SecretStr("pw-1"), groq_api_key=SecretStr("gsk_example")
    )
    assert sorted(settings.secret_values()) == ["gsk_example", "pw-1"]

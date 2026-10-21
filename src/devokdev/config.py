"""Typed settings, loaded from environment variables and the local .env file.

Every setting has the prefix DEVOKDEV_, so DEVOKDEV_REDIS_URL sets ``redis_url``.
Secrets are ``SecretStr``: they print as '**********' and must be unwrapped with
``get_secret_value()`` at the single place that needs them.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Free model providers from the design doc. M1 (the router) reads these; M0 only
# reports which ones are configured.
PROVIDER_KEY_FIELDS: tuple[str, ...] = (
    "groq_api_key",
    "cerebras_api_key",
    "openrouter_api_key",
    "google_api_key",
    "mistral_api_key",
    "cloudflare_api_token",
    "nvidia_api_key",
)


class Settings(BaseSettings):
    """All runtime configuration for Devo-K-Dev."""

    model_config = SettingsConfigDict(
        env_prefix="DEVOKDEV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "ci"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"

    # PostgreSQL with pgvector: Devo-K-Dev's own state (ADR-005)
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = "devokdev"
    postgres_password: SecretStr = SecretStr("")
    postgres_db: str = "devokdev"

    # Redis: event bus and quota counters (ADR-005)
    redis_url: str = "redis://127.0.0.1:6379/0"

    # Temporal: durable execution (ADR-014)
    temporal_address: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "devokdev-default"
    temporal_ui_url: str = "http://127.0.0.1:8233"

    # Free model providers (used from M1)
    groq_api_key: SecretStr | None = None
    cerebras_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    cloudflare_api_token: SecretStr | None = None
    cloudflare_account_id: str | None = None
    nvidia_api_key: SecretStr | None = None

    def postgres_conninfo(self) -> str:
        """A libpq connection string. make_conninfo quotes special characters safely."""
        return make_conninfo(
            host=self.postgres_host,
            port=self.postgres_port,
            user=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            dbname=self.postgres_db,
        )

    def configured_providers(self) -> list[str]:
        """Names of providers whose key is set and non-empty. Never returns key values."""
        names: list[str] = []
        for field in PROVIDER_KEY_FIELDS:
            value = getattr(self, field)
            if isinstance(value, SecretStr) and value.get_secret_value().strip():
                names.append(field.removesuffix("_api_key").removesuffix("_api_token"))
        return names

    def secret_values(self) -> list[str]:
        """Every non-empty secret, so error messages can be scrubbed before display."""
        secrets: list[str] = []
        for value in self.__dict__.values():
            if isinstance(value, SecretStr) and value.get_secret_value():
                secrets.append(value.get_secret_value())
        return secrets


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once. Tests build ``Settings(...)`` directly instead."""
    return Settings()

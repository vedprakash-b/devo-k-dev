"""Helpers shared by unit tests: a small registry with two fake providers."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from devokdev.config import Settings
from devokdev.llm.adapter import Endpoint, OpenAICompatAdapter, StreamTimeouts
from devokdev.llm.registry import Registry
from devokdev.llm.scripted import ScriptedTransport

# Two providers, three models. Names are unique on the wire so scripts are simple.
TEST_REGISTRY_YAML = """
version: 1
roles:
  backend: {class: coding, needs: [tools]}
  orchestrator: {class: reasoning}
  reviewer: {class: review, different_family: true}
  researcher: {class: reasoning, min_context: 100000}
  scribe: {class: light}
providers:
  alpha:
    base_url: https://alpha.test/v1
    key_setting: groq_api_key
    trains_on_prompts: false
    checked: 2026-10-26
    rate_limit_headers: {bare_windows: {requests: day, tokens: minute}}
    models:
      alpha-large:
        family: fam-a
        context_window: 131072
        max_output_tokens: 8192
        tools: true
        json_mode: true
        tiers: {coding: 5, reasoning: 4, review: 3, light: 2}
        limits: {rpm: 30, rpd: 1000, tpm: 8000}
      alpha-small:
        family: fam-a
        context_window: 32768
        max_output_tokens: 4096
        tools: true
        tiers: {coding: 2, light: 4}
  beta:
    base_url: https://beta.test/v1
    key_setting: cerebras_api_key
    trains_on_prompts: true
    checked: 2026-10-26
    shared_limits: {rpm: 20, rpd: 50}
    models:
      beta-coder:
        family: fam-b
        context_window: 65536
        max_output_tokens: 8192
        tools: true
        json_mode: true
        tiers: {coding: 4, reasoning: 3, review: 4, light: 3}
"""


def make_registry(text: str = TEST_REGISTRY_YAML) -> Registry:
    return Registry.from_yaml_text(text)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "groq_api_key": SecretStr("alpha-key"),
        "cerebras_api_key": SecretStr("beta-key"),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def endpoint(registry: Registry, provider: str, key: str = "test-key") -> Endpoint:
    spec = registry.providers[provider]
    return Endpoint(provider=spec, base_url=spec.base_url, api_key=key)


def make_adapter(
    transport: ScriptedTransport, timeouts: StreamTimeouts | None = None, now: float = 1_000_000.0
) -> OpenAICompatAdapter:
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatAdapter(client, timeouts or StreamTimeouts(), wall_clock=lambda: now)


class FakeClock:
    """Wall-clock time that only moves when a test says so."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    async def sleep(self, seconds: float) -> None:
        """Stands in for asyncio.sleep: records the wait and moves time on."""
        self.slept.append(seconds)
        self.now += seconds

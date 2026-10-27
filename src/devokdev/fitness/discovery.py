"""Discovery: which models does each provider serve today?

Free model catalogues change weekly. A model is renamed (Groq's ``qwen3.6-27b`` became
``qwen3.8-27b``), a free variant disappears, a better one appears. Discovery lists what
each configured provider serves (``GET /models``) and compares it with the registry, so
drift shows up as a report instead of as 404s in the middle of a run.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Literal

from devokdev.llm.adapter import Endpoint
from devokdev.llm.errors import ProviderError
from devokdev.router.gateway import Gateway


@dataclass(frozen=True, slots=True)
class DiscoveryReport:
    provider: str
    status: Literal["ok", "no_key", "not_supported", "error"]
    served: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()  # in the registry, not served any more
    new: tuple[str, ...] = ()  # served (and matching the filter), not in the registry
    error: str = ""
    registered: tuple[str, ...] = field(default=())


def _normalise(model_id: str) -> str:
    return model_id.removeprefix("models/")  # Google lists "models/gemini-..."


async def discover_provider(gateway: Gateway, provider_name: str) -> DiscoveryReport:
    registry = gateway.registry
    provider = registry.providers[provider_name]
    registered = tuple(
        sorted(m.name for m in registry.models.values() if m.provider == provider_name)
    )
    if not provider.discovery:
        return DiscoveryReport(provider_name, "not_supported", registered=registered)
    key = registry.api_key(provider, gateway.settings)
    url = registry.base_url(provider, gateway.settings)
    if key is None or url is None:
        return DiscoveryReport(provider_name, "no_key", registered=registered)
    endpoint = Endpoint(provider=provider, base_url=url, api_key=key.get_secret_value())
    try:
        served = tuple(_normalise(m) for m in await gateway.adapter.list_models(endpoint))
    except ProviderError as error:
        return DiscoveryReport(provider_name, "error", error=str(error), registered=registered)
    served_set = set(served)
    pattern = re.compile(provider.discovery_match) if provider.discovery_match else None
    new = tuple(
        sorted(
            m
            for m in served_set - set(registered)
            if pattern is None or pattern.search(m) is not None
        )
    )
    missing = tuple(m for m in registered if m not in served_set)
    return DiscoveryReport(provider_name, "ok", served, missing, new, registered=registered)


async def discover(gateway: Gateway) -> list[DiscoveryReport]:
    names = sorted(gateway.registry.providers)
    return list(await asyncio.gather(*(discover_provider(gateway, n) for n in names)))

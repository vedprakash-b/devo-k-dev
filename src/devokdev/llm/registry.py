"""The model registry: which providers and models exist, and what each can do.

It is loaded from ``config/models.yaml``, a file people edit, and validated strictly on
load: an unknown field, a model whose provider does not exist, or a role that points at a
missing class is an error at start-up, not a surprise in the middle of a run.

Three rules are encoded here:

- **Data policy fails safe.** ``trains_on_prompts`` defaults to True, so a provider whose
  policy we have not checked is treated as one that trains on prompts (ADR-008).
- **Roles map to classes.** Eighteen roles share five role classes (reasoning, coding,
  review, vision, light); each model has a quality tier per class. Adding a role means
  one line under ``roles``, not a tier on every model.
- **Limits live in two places.** ``limits`` on a model are per model; ``shared_limits``
  on a provider cover every model it serves (OpenRouter's free models share one quota).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devokdev.config import PROVIDER_KEY_FIELDS
from devokdev.llm.ratelimits import Dimension, Window

if TYPE_CHECKING:
    from pydantic import SecretStr

    from devokdev.config import Settings

SLUG = r"^[a-z0-9][a-z0-9_-]*$"
Tier = Annotated[int, Field(ge=0, le=5)]


class RoleClass(StrEnum):
    REASONING = "reasoning"  # plans and designs: Orchestrator, Analyst, Architect
    CODING = "coding"  # writes and runs code: engineers, QA, DevOps
    REVIEW = "review"  # judges others' work, ideally from another model family
    VISION = "vision"  # needs to see screenshots: UI Designer
    LIGHT = "light"  # summaries, chat, records: Scribe, Liaison, Intake


class Capability(StrEnum):
    TOOLS = "tools"
    JSON = "json"
    VISION = "vision"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Limits(_Strict):
    """Free-tier limits. Unset means unknown; the router then learns from headers."""

    rpm: int | None = Field(default=None, ge=1)
    rph: int | None = Field(default=None, ge=1)
    rpd: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    tph: int | None = Field(default=None, ge=1)
    tpd: int | None = Field(default=None, ge=1)

    def windows(self) -> list[tuple[Dimension, Window, int]]:
        table = {
            (Dimension.REQUESTS, Window.MINUTE): self.rpm,
            (Dimension.REQUESTS, Window.HOUR): self.rph,
            (Dimension.REQUESTS, Window.DAY): self.rpd,
            (Dimension.TOKENS, Window.MINUTE): self.tpm,
            (Dimension.TOKENS, Window.HOUR): self.tph,
            (Dimension.TOKENS, Window.DAY): self.tpd,
        }
        return [(dim, win, limit) for (dim, win), limit in table.items() if limit is not None]


class Quirks(_Strict):
    """How a provider departs from the OpenAI chat format. Defaults follow the spec."""

    # Some models reject a system role; its text is then prefixed to the first user turn.
    system_prompt: Literal["native", "merge_into_user"] = "native"
    # What to send as `content` on an assistant turn that only calls tools.
    assistant_tool_content: Literal["null", "empty_string"] = "null"
    # Whether tool-result messages carry the tool's `name`.
    tool_message_name: bool = False
    # Whether to ask for token usage in the last stream chunk.
    stream_usage: bool = True
    max_tokens_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


class RateLimitHeaderSpec(_Strict):
    """Which window headers without a -minute/-day suffix describe, per dimension."""

    bare_windows: dict[Dimension, Window] = Field(default_factory=dict)


class ModelEntry(_Strict):
    """A model as written in models.yaml (under its provider)."""

    family: str = Field(pattern=SLUG)
    context_window: int = Field(ge=1024)
    max_output_tokens: int = Field(ge=64)
    tools: bool = False
    json_mode: bool = False
    vision: bool = False
    tiers: dict[RoleClass, Tier] = Field(default_factory=dict)
    limits: Limits = Field(default_factory=Limits)
    trains_on_prompts: bool | None = None  # overrides the provider's value
    quirks: Quirks | None = None  # fields set here override the provider's quirks
    notes: str = ""


class ProviderEntry(_Strict):
    base_url: str = Field(pattern=r"^https://")
    key_setting: str
    trains_on_prompts: bool = True
    checked: date
    discovery: bool = True
    # Only report served models whose ID matches this regex (OpenRouter: free ones only).
    discovery_match: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    shared_limits: Limits = Field(default_factory=Limits)
    quirks: Quirks = Field(default_factory=Quirks)
    rate_limit_headers: RateLimitHeaderSpec = Field(default_factory=RateLimitHeaderSpec)
    notes: str = ""
    models: dict[str, ModelEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_key(self) -> ProviderEntry:
        if self.key_setting not in PROVIDER_KEY_FIELDS:
            raise ValueError(
                f"key_setting {self.key_setting!r} is not a provider key in config.Settings"
            )
        return self


class RoleSpec(_Strict):
    role_class: RoleClass = Field(alias="class")
    needs: tuple[Capability, ...] = ()
    min_context: int = Field(default=0, ge=0)
    # Reviewers should not share a model family with the author they review.
    different_family: bool = False


class RegistryFile(_Strict):
    version: Literal[1]
    roles: dict[str, RoleSpec]
    providers: dict[str, ProviderEntry]

    @model_validator(mode="after")
    def _slugs(self) -> RegistryFile:
        for name in (*self.roles, *self.providers):
            if not re.match(SLUG, name):
                raise ValueError(f"{name!r} must be lowercase letters, digits, - or _")
        return self


# ------------------------------------------------------------------ resolved views


class ProviderSpec(_Strict):
    name: str
    base_url: str
    key_setting: str
    trains_on_prompts: bool
    checked: date
    discovery: bool
    discovery_match: str
    headers: dict[str, str]
    shared_limits: Limits
    quirks: Quirks
    rate_limit_headers: RateLimitHeaderSpec
    notes: str = ""


class ModelSpec(_Strict):
    """A model with its provider resolved. ``id`` is ``<provider>/<provider's model name>``."""

    id: str
    provider: str
    name: str
    family: str
    context_window: int
    max_output_tokens: int
    tools: bool
    json_mode: bool
    vision: bool
    tiers: dict[RoleClass, int]
    limits: Limits
    trains_on_prompts: bool
    quirks: Quirks
    notes: str = ""

    def has(self, capability: Capability) -> bool:
        return {
            Capability.TOOLS: self.tools,
            Capability.JSON: self.json_mode,
            Capability.VISION: self.vision,
        }[capability]

    def tier(self, role_class: RoleClass) -> int:
        return self.tiers.get(role_class, 0)

    def fingerprint(self) -> str:
        """Changes whenever the registry entry changes, so cached profiles go stale."""
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class RegistryError(ValueError):
    """models.yaml is missing or invalid. The message says where."""


class Registry:
    def __init__(self, data: RegistryFile, source: Path | None = None) -> None:
        self.source = source
        self.roles: dict[str, RoleSpec] = dict(data.roles)
        self.providers: dict[str, ProviderSpec] = {}
        self.models: dict[str, ModelSpec] = {}
        for pname, pentry in data.providers.items():
            self.providers[pname] = ProviderSpec(
                name=pname, **pentry.model_dump(exclude={"models"})
            )
            for mname, mentry in pentry.models.items():
                trains = mentry.trains_on_prompts
                quirks = pentry.quirks
                if mentry.quirks is not None:
                    quirks = quirks.model_copy(update=mentry.quirks.model_dump(exclude_unset=True))
                spec = ModelSpec(
                    id=f"{pname}/{mname}",
                    provider=pname,
                    name=mname,
                    trains_on_prompts=pentry.trains_on_prompts if trains is None else trains,
                    quirks=quirks,
                    **mentry.model_dump(exclude={"trains_on_prompts", "quirks"}),
                )
                self.models[spec.id] = spec

    @classmethod
    def from_yaml_text(cls, text: str, source: Path | None = None) -> Registry:
        where = str(source) if source else "models.yaml"
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise RegistryError(f"{where} is not valid YAML: {exc}") from exc
        try:
            return cls(RegistryFile.model_validate(raw), source)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
            )
            raise RegistryError(f"{where} is invalid: {problems}") from exc

    @classmethod
    def load(cls, path: Path) -> Registry:
        if not path.is_file():
            raise RegistryError(f"model registry not found at {path}")
        return cls.from_yaml_text(path.read_text(encoding="utf-8"), path)

    def model(self, model_id: str) -> ModelSpec:
        try:
            return self.models[model_id]
        except KeyError:
            raise KeyError(f"unknown model {model_id!r}; see `devokdev models list`") from None

    def provider_of(self, model: ModelSpec) -> ProviderSpec:
        return self.providers[model.provider]

    def role(self, name: str) -> RoleSpec:
        try:
            return self.roles[name]
        except KeyError:
            known = ", ".join(sorted(self.roles))
            raise KeyError(f"unknown role {name!r}; known roles: {known}") from None

    def api_key(self, provider: ProviderSpec, settings: Settings) -> SecretStr | None:
        value: SecretStr | None = getattr(settings, provider.key_setting)
        if value is None or not value.get_secret_value().strip():
            return None
        return value

    def base_url(self, provider: ProviderSpec, settings: Settings) -> str | None:
        """The provider's URL with placeholders such as {cloudflare_account_id} filled in.

        None when a placeholder has no value, so the provider counts as unconfigured.
        """
        values = {k: v for k, v in settings.model_dump().items() if isinstance(v, str) and v}
        try:
            return provider.base_url.format(**values).rstrip("/")
        except KeyError:
            return None

    def usable_models(self, settings: Settings) -> list[ModelSpec]:
        """Models whose provider has a key (and a complete URL) in the current settings."""
        ready = {
            name
            for name, p in self.providers.items()
            if self.api_key(p, settings) and self.base_url(p, settings)
        }
        return [m for m in self.models.values() if m.provider in ready]

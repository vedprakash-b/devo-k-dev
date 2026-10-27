from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from devokdev.llm.registry import Capability, Registry, RegistryError, RoleClass
from tests.support import TEST_REGISTRY_YAML, make_registry, make_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_real_registry_file_is_valid() -> None:
    """config/models.yaml is loaded exactly as the router will load it."""
    registry = Registry.load(REPO_ROOT / "config" / "models.yaml")
    assert len(registry.models) >= 10
    assert "groq/openai/gpt-oss-120b" in registry.models
    for role in registry.roles.values():
        candidates = [m for m in registry.models.values() if m.tier(role.role_class) > 0]
        assert candidates, f"no model can play role class {role.role_class}"


def test_the_real_registry_keeps_training_providers_marked() -> None:
    registry = Registry.load(REPO_ROOT / "config" / "models.yaml")
    assert registry.model("google/gemini-3.5-flash-lite").trains_on_prompts
    assert not registry.model("groq/openai/gpt-oss-120b").trains_on_prompts


def test_model_ids_combine_provider_and_wire_name() -> None:
    registry = make_registry()
    model = registry.model("alpha/alpha-large")
    assert (model.provider, model.name) == ("alpha", "alpha-large")
    assert model.has(Capability.TOOLS)
    assert model.tier(RoleClass.CODING) == 5
    assert model.tier(RoleClass.VISION) == 0


def test_unknown_data_policy_counts_as_training() -> None:
    text = TEST_REGISTRY_YAML.replace("    trains_on_prompts: false\n", "")
    assert make_registry(text).model("alpha/alpha-large").trains_on_prompts


def test_model_quirks_override_only_the_fields_they_set() -> None:
    text = TEST_REGISTRY_YAML.replace(
        "    rate_limit_headers: {bare_windows: {requests: day, tokens: minute}}\n",
        "    rate_limit_headers: {bare_windows: {requests: day, tokens: minute}}\n"
        "    quirks: {tool_message_name: true}\n",
    ).replace(
        "        tiers: {coding: 2, light: 4}\n",
        "        tiers: {coding: 2, light: 4}\n        quirks: {system_prompt: merge_into_user}\n",
    )
    small = make_registry(text).model("alpha/alpha-small")
    assert small.quirks.system_prompt == "merge_into_user"
    assert small.quirks.tool_message_name  # inherited from the provider


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        (("family: fam-a", "family: Fam A"), "family"),
        (("key_setting: groq_api_key", "key_setting: groq_key"), "key_setting"),
        (("context_window: 32768", "context_window: 100"), "context_window"),
        (("tiers: {coding: 2, light: 4}", "tiers: {coding: 9}"), "tiers"),
        (("tiers: {coding: 2, light: 4}", "tiers: {cooking: 2}"), "tiers"),
        (("max_output_tokens: 4096", "max_output_tokens: 4096\n        colour: red"), "colour"),
        (("{class: coding, needs: [tools]}", "{class: plumbing}"), "class"),
        (("version: 1", "version: 2"), "version"),
    ],
)
def test_mistakes_in_the_file_are_reported_with_their_location(
    change: tuple[str, str], complaint: str
) -> None:
    with pytest.raises(RegistryError, match=complaint):
        make_registry(TEST_REGISTRY_YAML.replace(*change))


def test_broken_yaml_and_missing_files_are_reported() -> None:
    with pytest.raises(RegistryError, match="not valid YAML"):
        make_registry("version: [1")
    with pytest.raises(RegistryError, match="not found"):
        Registry.load(Path("/nonexistent/models.yaml"))


def test_usable_models_need_a_key_and_a_complete_url() -> None:
    registry = make_registry()
    only_alpha = make_settings(cerebras_api_key=SecretStr(" "))
    assert {m.provider for m in registry.usable_models(only_alpha)} == {"alpha"}
    text = TEST_REGISTRY_YAML.replace(
        "https://beta.test/v1", "https://beta.test/{cloudflare_account_id}/v1"
    )
    templated = make_registry(text)
    assert {m.provider for m in templated.usable_models(make_settings())} == {"alpha"}
    with_account = make_settings(cloudflare_account_id="acc123")
    assert templated.base_url(templated.providers["beta"], with_account) == (
        "https://beta.test/acc123/v1"
    )


def test_fingerprint_changes_when_an_entry_changes() -> None:
    before = make_registry().model("alpha/alpha-large").fingerprint()
    text = TEST_REGISTRY_YAML.replace("max_output_tokens: 8192", "max_output_tokens: 4096", 1)
    after = make_registry(text).model("alpha/alpha-large").fingerprint()
    assert before != after


def test_unknown_names_list_what_exists() -> None:
    registry = make_registry()
    with pytest.raises(KeyError, match="models list"):
        registry.model("alpha/nope")
    with pytest.raises(KeyError, match="backend"):
        registry.role("chef")

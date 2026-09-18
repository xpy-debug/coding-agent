"""Tests for the vendor presets and the models they register.

Assertions use membership rather than equality: ``tests/test_models.py``
registers a throwaway provider in the global registry, so exact provider
lists would depend on test execution order.
"""

from __future__ import annotations

from coding.ai.env import _ENV_KEYS
from coding.ai.models import get_models
from coding.ai.vendors import VENDOR_PRESETS, get_vendor_preset, get_vendor_presets


def test_presets_are_well_formed():
    """Every preset needs an id, a label and a usable endpoint."""
    assert VENDOR_PRESETS

    for preset in VENDOR_PRESETS:
        assert preset.id
        assert preset.label
        assert preset.base_url.startswith(("http://", "https://"))
        # The URL is handed to the OpenAI SDK verbatim, which appends
        # /chat/completions itself.
        assert not preset.base_url.endswith("/chat/completions")


def test_presets_have_env_var_mappings():
    """Otherwise environment auth silently falls back to CODING_API_KEY."""
    for preset in VENDOR_PRESETS:
        assert preset.id in _ENV_KEYS


def test_presets_register_models():
    """Each preset backs its picker entry with built-in models."""
    for preset in VENDOR_PRESETS:
        models = get_models(preset.id)
        assert models, f"{preset.id} has no built-in models"

        for model in models:
            assert model.provider == preset.id
            assert model.api == "openai-completions"
            assert model.base_url == preset.base_url


def test_third_party_models_avoid_openai_only_params():
    """DeepSeek and friends reject OpenAI-proprietary request fields.

    The compat flags are explicit rather than detected, because a user-supplied
    base URL override would defeat ``_detect_compat``'s substring matching.
    """
    models = get_models("deepseek")
    assert models

    for model in models:
        compat = model.compat
        assert compat is not None
        assert compat.supports_store is False
        assert compat.supports_developer_role is False
        assert compat.supports_reasoning_effort is False
        assert compat.supports_strict_mode is False
        assert compat.max_tokens_field == "max_tokens"


def test_get_vendor_preset_lookup():
    """Lookup by id, and None for anything else."""
    preset = get_vendor_preset("deepseek")
    assert preset is not None
    assert preset.label == "DeepSeek"

    assert get_vendor_preset("does-not-exist") is None


def test_get_vendor_presets_is_serializable():
    """The UI payload carries the fields the vendor picker needs."""
    payload = get_vendor_presets()
    assert [entry["id"] for entry in payload] == [preset.id for preset in VENDOR_PRESETS]

    for entry in payload:
        assert {"id", "label", "baseUrl", "apiKeyUrl"} <= set(entry)

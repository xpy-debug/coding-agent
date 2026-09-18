"""Tests for model resolution with fuzzy matching."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from coding.ai.types import Model
from coding.core.resolver import (
    DEFAULT_MODEL_PER_PROVIDER,
    ModelRegistry,
    ScopedModel,
    _is_alias,
    find_initial_model,
    parse_model_pattern,
    resolve_model_scope,
    restore_model_from_session,
    try_match_model,
)

# --- Test helpers ---


def _make_model(
    model_id: str,
    provider: str = "openai",
    name: str | None = None,
    **kwargs: object,
) -> Model:
    return Model(
        id=model_id,
        name=name or model_id,
        api="openai-completions",
        provider=provider,
        baseUrl="https://api.openai.com/v1",
        **kwargs,
    )


SAMPLE_MODELS = [
    _make_model("gpt-4.1", name="GPT-4.1"),
    _make_model("gpt-4.1-20250414", name="GPT-4.1 (20250414)"),
    _make_model("gpt-4o", name="GPT-4o"),
    _make_model("gpt-4o-20241120", name="GPT-4o (20241120)"),
    _make_model("o3-mini", provider="openai", name="o3-mini"),
    _make_model("deepseek-chat", provider="deepseek", name="DeepSeek Chat"),
]


# --- Alias detection ---


def test_is_alias():
    assert _is_alias("gpt-4.1") is True
    assert _is_alias("gpt-4.1-latest") is True
    assert _is_alias("gpt-4.1-20250414") is False
    assert _is_alias("o3-mini") is True


# --- try_match_model ---


def test_match_exact_id():
    model = try_match_model("gpt-4.1", SAMPLE_MODELS)
    assert model is not None
    assert model.id == "gpt-4.1"


def test_match_case_insensitive():
    model = try_match_model("GPT-4.1", SAMPLE_MODELS)
    assert model is not None
    assert model.id == "gpt-4.1"


def test_match_provider_slash_model():
    model = try_match_model("openai/gpt-4.1", SAMPLE_MODELS)
    assert model is not None
    assert model.id == "gpt-4.1"
    assert model.provider == "openai"

    deepseek = try_match_model("deepseek/deepseek-chat", SAMPLE_MODELS)
    assert deepseek is not None
    assert deepseek.provider == "deepseek"


def test_match_partial():
    model = try_match_model("4.1", SAMPLE_MODELS)
    assert model is not None
    # Should prefer alias over dated version
    assert model.id == "gpt-4.1"


def test_match_partial_4o():
    model = try_match_model("4o", SAMPLE_MODELS)
    assert model is not None
    assert model.id == "gpt-4o"


def test_match_not_found():
    model = try_match_model("nonexistent-model", SAMPLE_MODELS)
    assert model is None


def test_match_provider_not_found():
    model = try_match_model("unknown/model", SAMPLE_MODELS)
    assert model is None


# --- parse_model_pattern ---


def test_parse_plain_pattern():
    result = parse_model_pattern("gpt-4.1", SAMPLE_MODELS)
    assert result.model is not None
    assert result.model.id == "gpt-4.1"
    assert result.thinking_level is None


def test_parse_with_thinking_level():
    result = parse_model_pattern("gpt-4.1:high", SAMPLE_MODELS)
    assert result.model is not None
    assert result.model.id == "gpt-4.1"
    assert result.thinking_level == "high"


def test_parse_with_invalid_thinking_level():
    result = parse_model_pattern("gpt-4.1:invalid", SAMPLE_MODELS)
    assert result.model is not None
    assert result.warning is not None
    assert "Unknown thinking level" in result.warning


def test_parse_not_found():
    result = parse_model_pattern("nonexistent", SAMPLE_MODELS)
    assert result.model is None
    assert result.warning is not None


# --- resolve_model_scope ---


def test_resolve_single_pattern():
    scoped, warnings = resolve_model_scope(["gpt-4.1"], SAMPLE_MODELS)
    assert len(scoped) == 1
    assert scoped[0].model.id == "gpt-4.1"
    assert not warnings


def test_resolve_with_thinking_level():
    scoped, warnings = resolve_model_scope(["gpt-4.1:high"], SAMPLE_MODELS)
    assert len(scoped) == 1
    assert scoped[0].thinking_level == "high"
    assert not warnings


def test_resolve_glob_pattern():
    scoped, warnings = resolve_model_scope(["*gpt*"], SAMPLE_MODELS)
    assert len(scoped) == 4  # All 4 gpt models
    assert not warnings


def test_resolve_glob_no_match():
    scoped, warnings = resolve_model_scope(["*nonexistent*"], SAMPLE_MODELS)
    assert len(scoped) == 0
    assert len(warnings) == 1


def test_resolve_deduplication():
    scoped, _ = resolve_model_scope(
        ["gpt-4.1", "4.1"],
        SAMPLE_MODELS,
    )
    assert len(scoped) == 1  # Deduped


def test_resolve_multiple_patterns():
    scoped, warnings = resolve_model_scope(
        ["gpt-4.1", "o3-mini"],
        SAMPLE_MODELS,
    )
    assert len(scoped) == 2
    assert not warnings


# --- find_initial_model ---


def test_find_cli_provider_model():
    result = find_initial_model(
        models=SAMPLE_MODELS,
        cli_provider="openai",
        cli_model="gpt-4.1",
    )
    assert result.model is not None
    assert result.model.id == "gpt-4.1"


def test_find_cli_model_only():
    result = find_initial_model(
        models=SAMPLE_MODELS,
        cli_model="4.1",
    )
    assert result.model is not None
    assert result.model.id == "gpt-4.1"


def test_find_cli_model_not_found():
    result = find_initial_model(
        models=SAMPLE_MODELS,
        cli_model="nonexistent",
    )
    assert result.model is None
    assert result.fallback_message is not None


def test_find_scoped_model():
    scoped = [ScopedModel(model=SAMPLE_MODELS[0], thinking_level="high")]
    result = find_initial_model(
        models=SAMPLE_MODELS,
        scoped_models=scoped,
    )
    assert result.model is not None
    assert result.model.id == "gpt-4.1"
    assert result.thinking_level == "high"


def test_find_scoped_ignored_on_continue():
    scoped = [ScopedModel(model=SAMPLE_MODELS[0])]
    with patch("coding.core.resolver.get_env_api_key", return_value="key"):
        result = find_initial_model(
            models=SAMPLE_MODELS,
            scoped_models=scoped,
            is_continue=True,
        )
    # Should fall through to available model since no settings
    assert result.model is not None


def test_find_with_api_key():
    with patch("coding.core.resolver.get_env_api_key", return_value="key"):
        result = find_initial_model(models=SAMPLE_MODELS)
    assert result.model is not None


def test_find_no_models():
    result = find_initial_model(models=[])
    assert result.model is None
    assert result.fallback_message is not None


# --- restore_model_from_session ---


def test_restore_exact():
    with patch("coding.core.resolver.get_env_api_key", return_value="key"):
        result = restore_model_from_session(
            provider="openai",
            model_id="gpt-4.1",
            models=SAMPLE_MODELS,
        )
    assert result.model is not None
    assert result.model.id == "gpt-4.1"


def test_restore_no_key():
    with patch("coding.core.resolver.get_env_api_key", return_value=None):
        result = restore_model_from_session(
            provider="openai",
            model_id="gpt-4.1",
            models=SAMPLE_MODELS,
        )
    assert result.model is None
    assert result.fallback_message is not None


def test_restore_model_not_found_fallback():
    with patch("coding.core.resolver.get_env_api_key", return_value="key"):
        result = restore_model_from_session(
            provider="openai",
            model_id="deleted-model",
            models=SAMPLE_MODELS,
        )
    # Should fallback to default for provider or first available
    assert result.model is not None
    assert result.fallback_message is not None


# --- ModelRegistry ---


def test_registry_register_and_find():
    registry = ModelRegistry.__new__(ModelRegistry)
    registry._models = {}
    registry._providers = {}
    registry._custom_errors = []

    model = _make_model("test-model")
    registry.register(model)

    found = registry.find("openai", "test-model")
    assert found is not None
    assert found.id == "test-model"


def test_registry_get_all():
    registry = ModelRegistry.__new__(ModelRegistry)
    registry._models = {}
    registry._providers = {}
    registry._custom_errors = []

    registry.register(_make_model("m1"))
    registry.register(_make_model("m2"))
    assert len(registry.get_all()) == 2


def test_registry_register_provider():
    registry = ModelRegistry.__new__(ModelRegistry)
    registry._models = {}
    registry._providers = {}
    registry._custom_errors = []

    registry.register_provider(
        "test-provider",
        base_url="https://test.com",
        api="openai-completions",
        models=[
            {"id": "model-a", "name": "Model A"},
            {"id": "model-b", "name": "Model B"},
        ],
    )

    assert len(registry.get_models_for_provider("test-provider")) == 2
    assert "test-provider" in registry.get_providers()


def test_registry_custom_models_from_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "providers": {
                "my-provider": {
                    "baseUrl": "https://my.api.com",
                    "api": "openai-completions",
                    "models": [
                        {
                            "id": "my-model",
                            "name": "My Model",
                            "contextWindow": 128000,
                            "maxTokens": 4096,
                        }
                    ],
                }
            }
        }
        Path(os.path.join(tmpdir, "models.json")).write_text(json.dumps(config), encoding="utf-8")

        registry = ModelRegistry(agent_dir=tmpdir)
        model = registry.find("my-provider", "my-model")
        assert model is not None
        assert model.name == "My Model"
        assert model.context_window == 128000


def test_registry_invalid_models_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(os.path.join(tmpdir, "models.json")).write_text("not json", encoding="utf-8")

        registry = ModelRegistry(agent_dir=tmpdir)
        assert len(registry.get_custom_errors()) > 0


# --- DEFAULT_MODEL_PER_PROVIDER ---


def test_default_model_per_provider_has_entries():
    assert len(DEFAULT_MODEL_PER_PROVIDER) >= 1
    assert "openai" in DEFAULT_MODEL_PER_PROVIDER

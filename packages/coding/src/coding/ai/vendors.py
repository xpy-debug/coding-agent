"""Preset LLM vendors.

Every vendor here speaks the OpenAI Chat Completions API, so ``base_url`` is
the only thing a preset adds on top of the model definitions in
:mod:`coding.ai.models_builtin`. This module is the single source of truth for the
vendor picker in the web UI *and* for the default endpoints used when
registering the built-in models.

Vendor ``id`` doubles as ``Model.provider`` and **must** match a key in
:data:`coding.ai.env._ENV_KEYS`, otherwise environment-based authentication
silently falls back to ``CODING_API_KEY``.
"""

from __future__ import annotations

from dataclasses import dataclass

from coding.ai.types import OpenAICompletionsCompat

OPENAI_BASE_URL = "https://api.openai.com/v1"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# Anything that is not OpenAI itself rejects OpenAI's proprietary request
# fields. Detection in ``_detect_compat`` cannot be relied on here: it keys off
# provider names and base-URL substrings, which a user-supplied endpoint never
# matches (and a per-provider base URL override would defeat anyway). Spell the
# flags out for every endpoint we do not own: preset vendors and the models
# discovered behind a custom base URL.
#
# Thinking mode is left to the server default -- ``reasoning_effort`` and the
# vendor-private ``thinking`` params are never sent. Reasoning output is still
# parsed and rendered; the parser is not gated by these flags.
THIRD_PARTY_COMPAT = OpenAICompletionsCompat(
    supports_store=False,
    supports_developer_role=False,
    supports_reasoning_effort=False,
    max_tokens_field="max_tokens",
    supports_strict_mode=False,
)


@dataclass(frozen=True)
class VendorPreset:
    """A vendor whose API is OpenAI-compatible."""

    id: str
    label: str
    base_url: str
    api_key_url: str = ""


VENDOR_PRESETS: tuple[VendorPreset, ...] = (
    VendorPreset(
        id="openai",
        label="OpenAI",
        base_url=OPENAI_BASE_URL,
        api_key_url="https://platform.openai.com/api-keys",
    ),
    VendorPreset(
        id="deepseek",
        label="DeepSeek",
        base_url=DEEPSEEK_BASE_URL,
        api_key_url="https://platform.deepseek.com/api_keys",
    ),
)


def get_vendor_preset(vendor_id: str) -> VendorPreset | None:
    """Look up a preset by vendor id."""
    for preset in VENDOR_PRESETS:
        if preset.id == vendor_id:
            return preset
    return None


def get_vendor_presets() -> list[dict[str, str]]:
    """Get the vendor catalog as JSON-serializable dicts for the UI."""
    return [
        {
            "id": preset.id,
            "label": preset.label,
            "baseUrl": preset.base_url,
            "apiKeyUrl": preset.api_key_url,
        }
        for preset in VENDOR_PRESETS
    ]

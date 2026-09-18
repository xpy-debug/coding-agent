"""Built-in model definitions.

Only OpenAI-compatible models are defined here. All of them use the
``openai-completions`` API. To target a third-party OpenAI-compatible
endpoint, construct a :class:`~coding.ai.types.Model` with a custom
``base_url`` and ``provider`` name.
"""

from __future__ import annotations

from coding.ai.models import register_models
from coding.ai.types import Model, ModelCost, OpenAICompletionsCompat
from coding.ai.vendors import DEEPSEEK_BASE_URL, OPENAI_BASE_URL, THIRD_PARTY_COMPAT

_OPENAI_BASE = OPENAI_BASE_URL

# Reasoning models reject ``max_tokens`` and require ``max_completion_tokens``.
_REASONING_COMPAT = OpenAICompletionsCompat(max_tokens_field="max_completion_tokens")


def _m(
    id: str,
    name: str,
    *,
    api: str = "openai-completions",
    provider: str = "openai",
    base_url: str = _OPENAI_BASE,
    reasoning: bool = False,
    input: list[str] | None = None,
    cost_in: float = 0,
    cost_out: float = 0,
    cache_read: float = 0,
    cache_write: float = 0,
    context_window: int = 0,
    max_tokens: int = 0,
    headers: dict[str, str] | None = None,
    compat: OpenAICompletionsCompat | None = None,
) -> Model:
    return Model(
        id=id,
        name=name,
        api=api,
        provider=provider,
        baseUrl=base_url,
        reasoning=reasoning,
        input=input or ["text"],
        cost=ModelCost(input=cost_in, output=cost_out, cacheRead=cache_read, cacheWrite=cache_write),
        contextWindow=context_window,
        maxTokens=max_tokens,
        headers=headers,
        compat=compat,
    )


# ---------------------------------------------------------------------------
# OpenAI (Chat Completions API)
# ---------------------------------------------------------------------------
_OPENAI_MODELS: dict[str, Model] = {}

for _id, _name, _reasoning, _inp, _cost_in, _cost_out, _cr, _ctx, _mt, _compat in [
    ("gpt-4.1", "GPT-4.1", False, ["text", "image"], 2, 8, 0.5, 1047576, 32768, None),
    ("gpt-4.1-mini", "GPT-4.1 mini", False, ["text", "image"], 0.4, 1.6, 0.1, 1047576, 32768, None),
    ("gpt-4.1-nano", "GPT-4.1 nano", False, ["text", "image"], 0.1, 0.4, 0.03, 1047576, 32768, None),
    ("gpt-4o", "GPT-4o", False, ["text", "image"], 2.5, 10, 1.25, 128000, 16384, None),
    ("gpt-4o-mini", "GPT-4o mini", False, ["text", "image"], 0.15, 0.6, 0.08, 128000, 16384, None),
    ("o4-mini", "o4-mini", True, ["text", "image"], 1.1, 4.4, 0.28, 200000, 100000, _REASONING_COMPAT),
    ("o3-mini", "o3-mini", True, ["text"], 1.1, 4.4, 0.55, 200000, 100000, _REASONING_COMPAT),
]:
    _OPENAI_MODELS[_id] = _m(
        _id,
        _name,
        reasoning=_reasoning,
        input=_inp,
        cost_in=_cost_in,
        cost_out=_cost_out,
        cache_read=_cr,
        context_window=_ctx,
        max_tokens=_mt,
        compat=_compat,
    )


# ---------------------------------------------------------------------------
# DeepSeek (Chat Completions API)
# ---------------------------------------------------------------------------

# Model IDs are a moving target: the ``deepseek-chat`` / ``deepseek-reasoner``
# aliases were retired on 2026-07-24. These entries are only the offline
# fallback -- the web UI refreshes the real list from ``GET /models`` with the
# user's key (see ``coding.web.model_discovery``). The IDs below are what that
# endpoint reports as of 2026-09-17; when they drift again, discovery corrects
# them and these only matter for a user who is offline.
_DEEPSEEK_MODELS: dict[str, Model] = {}

for _id, _name, _inp, _cost_in, _cost_out, _cache_read, _ctx, _mt in [
    ("deepseek-flash", "DeepSeek Flash", ["text"], 0.28, 0.42, 0.028, 1000000, 32768),
    ("deepseek-v4-pro", "DeepSeek V4 Pro", ["text"], 0.28, 0.42, 0.028, 1000000, 32768),
]:
    _DEEPSEEK_MODELS[_id] = _m(
        _id,
        _name,
        provider="deepseek",
        base_url=DEEPSEEK_BASE_URL,
        reasoning=False,
        input=_inp,
        cost_in=_cost_in,
        cost_out=_cost_out,
        cache_read=_cache_read,
        context_window=_ctx,
        max_tokens=_mt,
        compat=THIRD_PARTY_COMPAT,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_builtin_models() -> None:
    """Register all built-in models."""
    register_models("openai", _OPENAI_MODELS)
    register_models("deepseek", _DEEPSEEK_MODELS)

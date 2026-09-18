"""Environment-based API key resolution.

Only OpenAI-compatible providers are supported. Any provider registered by a
Model can have its key supplied explicitly (settings/DB); this module provides
the environment-variable fallback.
"""

from __future__ import annotations

import os

# Provider id -> environment variable holding its API key.
_ENV_KEYS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "xai": "XAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "zai": "ZAI_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "minimax-cn": "MINIMAX_CN_API_KEY",
    "huggingface": "HF_TOKEN",
    "together": "TOGETHER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "qwen": "DASHSCOPE_API_KEY",
    "dashscope": "DASHSCOPE_API_KEY",
    "siliconflow": "SILICONFLOW_API_KEY",
    "doubao": "ARK_API_KEY",
    "volcengine": "ARK_API_KEY",
}

# Generic fallback for custom OpenAI-compatible endpoints.
_FALLBACK_KEY = "CODING_API_KEY"


def get_env_api_key(provider: str) -> str | None:
    """Get the API key for a provider from the environment.

    Falls back to ``CODING_API_KEY`` for custom OpenAI-compatible providers.
    Returns ``None`` when no key is configured.
    """
    env_var = _ENV_KEYS.get(provider)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return os.environ.get(_FALLBACK_KEY) or None

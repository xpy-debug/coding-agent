"""Register built-in API providers.

Only the OpenAI Chat Completions API is supported. This covers the official
OpenAI API as well as any third-party endpoint that implements the
``/chat/completions`` contract (DeepSeek, Moonshot/Kimi, Zhipu/GLM, Qwen,
OpenRouter, Groq, xAI, vLLM, Ollama, ...). Point ``Model.base_url`` at the
desired endpoint to use a compatible provider.
"""

from __future__ import annotations

from coding.ai.providers.openai_completions import (
    stream_openai_completions,
    stream_simple_openai_completions,
)
from coding.ai.registry import ApiProvider, register_api_provider


def register_builtin_providers() -> None:
    """Register the built-in LLM API providers."""
    register_api_provider(
        ApiProvider(
            api="openai-completions",
            stream=stream_openai_completions,
            stream_simple=stream_simple_openai_completions,
        )
    )

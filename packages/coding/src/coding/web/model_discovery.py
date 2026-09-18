"""Discover the models an OpenAI-compatible endpoint serves.

Used by the web UI so a user only has to paste an API key (and, for a custom
endpoint, a base URL) before the model picker can be populated from
``GET {base_url}/models``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# The OpenAI SDK refuses to build a client without a key. Local endpoints
# (Ollama, vLLM, ...) usually have no auth at all, so send a placeholder.
_PLACEHOLDER_KEY = "none"

_TIMEOUT_SECONDS = 10.0


class ModelDiscoveryError(Exception):
    """Raised when an endpoint's model list cannot be retrieved."""


async def discover_model_ids(base_url: str, api_key: str = "") -> list[str]:
    """Fetch the model IDs served by ``base_url``.

    ``base_url`` is used verbatim, exactly like ``Model.base_url`` is passed to
    the OpenAI SDK when streaming (``coding/ai/providers/openai_completions.py``):
    the SDK appends ``/models`` itself, so the URL must not include it.

    Raises :class:`ModelDiscoveryError` if the endpoint cannot be reached or
    does not answer with a model list.
    """
    import openai

    base_url = (base_url or "").strip()
    if not base_url:
        raise ModelDiscoveryError("Base URL is required")

    client = openai.AsyncOpenAI(
        api_key=api_key or _PLACEHOLDER_KEY,
        base_url=base_url,
        timeout=_TIMEOUT_SECONDS,
        max_retries=1,
    )
    try:
        response = await client.models.list()
    except Exception as e:
        logger.info("Model discovery failed for %s: %s", base_url, e)
        raise ModelDiscoveryError(f"Could not fetch models from {base_url}: {e}") from e
    finally:
        await client.close()

    ids: list[str] = []
    for model in response.data or []:
        model_id = getattr(model, "id", "") or ""
        if model_id and model_id not in ids:
            ids.append(model_id)
    return ids

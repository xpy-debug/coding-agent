"""Tests for environment-based API key resolution."""

import os
from unittest.mock import patch

from coding.ai.env import get_env_api_key


def test_openai_key():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai"}, clear=False):
        assert get_env_api_key("openai") == "sk-openai"


def test_deepseek_key():
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-deepseek"}, clear=False):
        assert get_env_api_key("deepseek") == "sk-deepseek"


def test_unknown_provider_without_fallback():
    env = {k: v for k, v in os.environ.items() if k not in ("CODING_API_KEY",)}
    with patch.dict(os.environ, env, clear=True):
        assert get_env_api_key("unknown-provider") is None


def test_generic_fallback_key():
    with patch.dict(os.environ, {"CODING_API_KEY": "sk-custom"}, clear=False):
        assert get_env_api_key("my-custom-endpoint") == "sk-custom"

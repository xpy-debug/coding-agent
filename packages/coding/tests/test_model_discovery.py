"""Tests for endpoint model discovery."""

from __future__ import annotations

from types import SimpleNamespace

import openai
import pytest

from coding.web.model_discovery import ModelDiscoveryError, discover_model_ids


class _FakeModels:
    def __init__(self, model_ids: list[str]) -> None:
        self._model_ids = model_ids

    async def list(self):
        return SimpleNamespace(data=[SimpleNamespace(id=i) for i in self._model_ids])


class _FakeClient:
    """Stands in for ``openai.AsyncOpenAI``."""

    def __init__(self, model_ids: list[str] | None = None, error: Exception | None = None):
        # model_ids/error are test knobs, not client options.
        self._model_ids = model_ids or []
        self._error = error
        self.options: dict = {}
        self.closed = False

    @property
    def models(self) -> _FakeModels:
        if self._error is not None:
            raise self._error
        return _FakeModels(self._model_ids)

    async def close(self) -> None:
        self.closed = True


def install(monkeypatch, client: _FakeClient) -> _FakeClient:
    """Make ``openai.AsyncOpenAI(...)`` hand out ``client``."""

    def _factory(**options):
        client.options = options
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", _factory)
    return client


@pytest.fixture
def fake_client(monkeypatch):
    """Install a fake OpenAI client that serves two models."""
    return install(monkeypatch, _FakeClient(model_ids=["model-a", "model-b"]))


async def test_discover_returns_model_ids(fake_client):
    ids = await discover_model_ids("https://api.example.com/v1", "sk-test")
    assert ids == ["model-a", "model-b"]


async def test_discover_passes_endpoint_and_key_through(fake_client):
    """The base URL reaches the SDK verbatim, which appends /models itself."""
    await discover_model_ids("https://api.example.com/v1", "sk-test")

    assert fake_client.options["base_url"] == "https://api.example.com/v1"
    assert fake_client.options["api_key"] == "sk-test"


async def test_discover_uses_placeholder_key(monkeypatch):
    """Keyless local endpoints still need a non-empty key for the SDK."""
    client = install(monkeypatch, _FakeClient(model_ids=["llama3"]))

    await discover_model_ids("http://localhost:11434/v1")
    assert client.options["api_key"]


async def test_discover_closes_the_client(fake_client):
    await discover_model_ids("https://api.example.com/v1", "sk-test")
    assert fake_client.closed is True


async def test_discover_deduplicates_ids(monkeypatch):
    install(monkeypatch, _FakeClient(model_ids=["model-a", "model-a", "model-b"]))

    assert await discover_model_ids("https://api.example.com/v1") == ["model-a", "model-b"]


async def test_discover_requires_a_base_url():
    with pytest.raises(ModelDiscoveryError):
        await discover_model_ids("")


async def test_discover_wraps_endpoint_failures(monkeypatch):
    install(monkeypatch, _FakeClient(error=RuntimeError("connection refused")))

    with pytest.raises(ModelDiscoveryError) as excinfo:
        await discover_model_ids("https://api.example.com/v1")
    assert "connection refused" in str(excinfo.value)

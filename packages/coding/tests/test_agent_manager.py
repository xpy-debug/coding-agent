"""Tests for AgentManager provider/model wiring.

These exercise the paths the web UI drives: the vendor catalog in the models
payload, API key storage, custom endpoints and their discovered models.
Model discovery is stubbed out so no test touches the network.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from coding.agent.types import ToolApprovalRequest
from coding.web import agent_manager as agent_manager_module
from coding.web.agent_manager import AgentManager
from coding.web.model_discovery import ModelDiscoveryError

if TYPE_CHECKING:
    from coding.web.storage.database import Database


@pytest.fixture
def no_env_keys(monkeypatch):
    """Ignore whatever API keys this machine happens to export."""
    monkeypatch.setattr(agent_manager_module, "get_env_api_key", lambda provider: None)
    return None


@pytest.fixture
def failing_discovery(monkeypatch):
    """Simulate an endpoint that does not expose a model list."""

    async def _discover(base_url: str, api_key: str = "") -> list[str]:
        raise ModelDiscoveryError(f"Could not fetch models from {base_url}")

    monkeypatch.setattr(agent_manager_module, "discover_model_ids", _discover)
    return None


@pytest.fixture
def discovered_models(monkeypatch):
    """Simulate an endpoint that serves two models."""
    ids = ["local-model-a", "local-model-b"]

    async def _discover(base_url: str, api_key: str = "") -> list[str]:
        return list(ids)

    monkeypatch.setattr(agent_manager_module, "discover_model_ids", _discover)
    return ids


def make_manager(db: Database, tmp_path) -> AgentManager:
    """Build a manager that reads no real ~/.coding configuration."""
    return AgentManager(db, default_workspace=str(tmp_path), agent_dir=str(tmp_path))


@pytest.fixture
def sent_messages():
    return []


@pytest.fixture
async def manager(db: Database, tmp_path, no_env_keys, sent_messages):
    manager = make_manager(db, tmp_path)

    async def collect(data):
        sent_messages.append(data)

    manager.set_send(collect)
    # The websocket handler does this on connect; it is what populates the
    # registry from the built-in models.
    await manager.load_preferences()
    return manager


# ---------------------------------------------------------------------------
# Models payload
# ---------------------------------------------------------------------------


async def test_models_payload_lists_vendors(manager: AgentManager):
    payload = await manager.get_models_dict()

    assert [vendor["id"] for vendor in payload["vendors"]] == ["openai", "deepseek"]
    assert payload["configuredProviders"] == []


async def test_models_payload_lists_every_provider(manager: AgentManager):
    payload = await manager.get_models_dict()

    providers = [entry["name"] for entry in payload["providers"]]
    assert "openai" in providers
    assert "deepseek" in providers


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


async def test_set_api_key_marks_provider_configured(
    manager: AgentManager, failing_discovery
):
    """A saved key shows up in the payload even when discovery fails."""
    await manager.set_api_key("deepseek", "sk-deepseek")

    payload = await manager.get_models_dict()
    assert payload["configuredProviders"] == ["deepseek"]
    assert await manager._has_key("deepseek") is True


async def test_set_api_key_keeps_builtin_models_when_discovery_fails(
    manager: AgentManager, failing_discovery
):
    """A provider without a usable /models endpoint still offers its models."""
    await manager.set_api_key("deepseek", "sk-deepseek")

    model_ids = [m.id for m in manager._registry.get_models_for_provider("deepseek")]
    assert model_ids


async def test_set_api_key_switches_off_unauthenticated_model(
    manager: AgentManager, failing_discovery
):
    """Entering a key for a new provider makes that provider usable at once."""
    await manager.new_session()
    assert manager.agent.state.model.provider == "openai"

    await manager.set_api_key("deepseek", "sk-deepseek")

    assert manager.agent.state.model.provider == "deepseek"


async def test_set_api_key_switches_even_if_the_old_provider_has_a_key(
    manager: AgentManager, failing_discovery
):
    """A stored key must not pin the session to the provider it is filed under.

    That key can be stale or, as with one entered before the vendor picker
    existed, filed under ``openai`` while belonging to someone else entirely --
    and its endpoint may not even be reachable.
    """
    await manager.new_session()
    await manager.set_api_key("openai", "sk-filed-under-the-wrong-provider")
    assert manager.agent.state.model.provider == "openai"

    await manager.set_api_key("deepseek", "sk-deepseek")

    assert manager.agent.state.model.provider == "deepseek"


async def test_new_session_keeps_the_last_selected_model(manager: AgentManager):
    """A new chat must not fall back to whichever provider registered first."""
    await manager.new_session()
    await manager.set_model("deepseek", "deepseek-v4-pro")

    await manager.new_session()

    assert manager.agent.state.model.id == "deepseek-v4-pro"


async def test_selected_model_survives_a_restart(db: Database, tmp_path, no_env_keys):
    first = make_manager(db, tmp_path)
    await first.load_preferences()
    await first.new_session()
    await first.set_model("deepseek", "deepseek-v4-pro")

    restarted = make_manager(db, tmp_path)
    await restarted.new_session()

    assert restarted.agent.state.model.id == "deepseek-v4-pro"


async def test_delete_api_key_clears_provider(manager: AgentManager, failing_discovery):
    await manager.set_api_key("deepseek", "sk-deepseek")
    await manager.delete_api_key("deepseek")

    payload = await manager.get_models_dict()
    assert payload["configuredProviders"] == []
    assert await manager._has_key("deepseek") is False


# ---------------------------------------------------------------------------
# Custom endpoints
# ---------------------------------------------------------------------------


async def test_custom_endpoint_registers_discovered_models(
    manager: AgentManager, discovered_models
):
    saved = await manager.set_custom_endpoint("http://localhost:11434/v1", "")

    assert saved is True
    payload = await manager.get_models_dict()
    assert "custom" in [entry["name"] for entry in payload["providers"]]
    assert payload["configuredProviders"] == ["custom"]

    base_urls = payload["baseUrls"]
    assert base_urls["custom"] == "http://localhost:11434/v1"

    for model_id in discovered_models:
        model = manager._registry.find("custom", model_id)
        assert model is not None
        assert model.base_url == "http://localhost:11434/v1"


async def test_discovered_models_avoid_openai_only_params(
    manager: AgentManager, discovered_models
):
    """``/models`` says nothing about tolerating OpenAI-only request fields.

    Without an explicit compat profile the provider name ``custom`` matches no
    rule in ``_detect_compat``, and we would send ``store`` and per-tool
    ``strict`` to an endpoint we know nothing about.
    """
    await manager.set_custom_endpoint("http://localhost:11434/v1", "")

    model = manager._registry.find("custom", "local-model-a")
    assert model is not None
    assert model.compat is not None
    assert model.compat.supports_store is False
    assert model.compat.supports_strict_mode is False
    assert model.compat.supports_developer_role is False
    assert model.compat.supports_reasoning_effort is False
    assert model.compat.max_tokens_field == "max_tokens"


async def test_custom_endpoint_needs_no_api_key(
    manager: AgentManager, discovered_models
):
    """Keyless local servers count as configured, so prompts do not re-prompt."""
    await manager.set_custom_endpoint("http://localhost:11434/v1", "")

    assert await manager._has_key("custom") is True
    # The OpenAI SDK refuses an empty key; it gets a placeholder instead.
    assert await manager._get_api_key("custom")


async def test_custom_endpoint_reports_discovery_failure(
    manager: AgentManager, failing_discovery, sent_messages
):
    saved = await manager.set_custom_endpoint("http://localhost:9999/v1", "")

    assert saved is False
    assert await manager._keys.exists("custom") is False
    assert any(message.get("type") == "error" for message in sent_messages)


async def test_custom_endpoint_requires_a_base_url(
    manager: AgentManager, sent_messages
):
    assert await manager.set_custom_endpoint("   ") is False
    assert any(message.get("type") == "error" for message in sent_messages)


async def test_discovered_models_survive_a_restart(
    db: Database, tmp_path, no_env_keys, discovered_models
):
    """The model list is persisted, not refetched on every page load."""
    first = make_manager(db, tmp_path)
    await first.set_custom_endpoint("http://localhost:11434/v1", "")

    restarted = make_manager(db, tmp_path)
    await restarted.load_preferences()

    assert restarted._registry.find("custom", "local-model-a") is not None
    assert await restarted._has_key("custom") is True


# ---------------------------------------------------------------------------
# Tool approval
# ---------------------------------------------------------------------------


async def _wait_for_sent_type(sent_messages: list, message_type: str) -> None:
    for _ in range(50):
        if any(message.get("type") == message_type for message in sent_messages):
            return
        await asyncio.sleep(0)
    raise AssertionError(f"{message_type} was never sent")


async def test_approval_mode_defaults_to_auto(manager: AgentManager):
    assert manager.approval_mode == "auto"
    assert manager.get_state_dict()["approvalMode"] == "auto"


async def test_set_approval_mode_is_remembered(manager: AgentManager):
    await manager.set_approval_mode("ask")

    assert manager.approval_mode == "ask"
    assert manager.get_state_dict()["approvalMode"] == "ask"
    assert await manager._settings.get("approval_mode") == "ask"


async def test_set_approval_mode_rejects_unknown_values(
    manager: AgentManager, sent_messages
):
    await manager.set_approval_mode("yolo")

    assert manager.approval_mode == "auto"
    assert any(message.get("type") == "error" for message in sent_messages)


async def test_approval_is_denied_when_no_client_can_answer(
    db: Database, tmp_path, no_env_keys
):
    """Fail closed: without a client, a gated call must not run."""
    manager = make_manager(db, tmp_path)
    request = ToolApprovalRequest(tool_call_id="call_1", tool_name="bash", args={})

    decision = await manager._request_tool_approval(request, "Shell commands can run anything")

    assert decision.approved is False
    assert "No client" in decision.reason


async def test_approval_round_trip_reaches_the_client(
    manager: AgentManager, sent_messages
):
    await manager.new_session()
    request = ToolApprovalRequest(tool_call_id="call_1", tool_name="bash", args={"command": "ls"})

    task = asyncio.ensure_future(
        manager._request_tool_approval(request, "Shell commands can run anything")
    )
    await _wait_for_sent_type(sent_messages, "tool_approval_request")

    sent = sent_messages[-1]
    assert sent["toolName"] == "bash"
    assert sent["args"] == {"command": "ls"}
    assert sent["reason"] == "Shell commands can run anything"

    assert manager.resolve_approval("call_1", True, True, "") is True
    decision = await task

    assert decision.approved is True
    assert decision.always_allow_tool is True


async def test_resolve_approval_ignores_unknown_ids(manager: AgentManager):
    assert manager.resolve_approval("nonexistent", True, False, "") is False


async def test_abort_denies_waiting_approvals(manager: AgentManager, sent_messages):
    await manager.new_session()
    request = ToolApprovalRequest(tool_call_id="call_1", tool_name="bash", args={})
    task = asyncio.ensure_future(manager._request_tool_approval(request, "reason"))
    await _wait_for_sent_type(sent_messages, "tool_approval_request")

    manager.abort()

    assert (await task).approved is False


async def test_cleanup_denies_approvals_still_waiting(
    manager: AgentManager, sent_messages
):
    await manager.new_session()
    request = ToolApprovalRequest(tool_call_id="call_1", tool_name="bash", args={})
    task = asyncio.ensure_future(manager._request_tool_approval(request, "reason"))
    await _wait_for_sent_type(sent_messages, "tool_approval_request")

    await manager.cleanup()
    decision = await task

    assert decision.approved is False
    assert "disconnected" in decision.reason


async def test_start_prompt_does_not_block_the_caller(manager: AgentManager, monkeypatch):
    started = asyncio.Event()

    async def fake_prompt(text: str) -> None:
        started.set()

    monkeypatch.setattr(manager, "prompt", fake_prompt)

    manager.start_prompt("hello")

    assert manager.is_running is True
    await manager._run_task
    assert started.is_set()
    assert manager.is_running is False

"""Agent lifecycle management per WebSocket session.

Wires the coding agent runtime (:class:`~coding.core.session.AgentSession`)
to the web layer. Each connection owns one session with the coding tools
(bash/read/write/edit/grep/find/ls) rooted at a configurable workspace.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import suppress
from typing import Any, cast

from coding.agent import Agent, AgentEvent, ThinkingLevel
from coding.agent.types import AgentState, ApprovalMode, ToolApprovalDecision, ToolApprovalRequest
from coding.ai.env import get_env_api_key
from coding.ai.models import get_models, get_providers
from coding.ai.types import Model
from coding.ai.vendors import THIRD_PARTY_COMPAT, get_vendor_preset, get_vendor_presets
from coding.core.approval import DEFAULT_APPROVAL_MODE, VALID_APPROVAL_MODES
from coding.core.resolver import ModelRegistry
from coding.core.session import AgentSession, AgentSessionConfig
from coding.core.sessions import SessionManager
from coding.core.settings import SettingsManager
from coding.web.model_discovery import ModelDiscoveryError, discover_model_ids
from coding.web.storage.database import Database
from coding.web.storage.provider_keys import ProviderKeyStore
from coding.web.storage.sessions import SessionStore
from coding.web.storage.settings import SettingsStore
from coding.web.ws.protocol import tool_approval_request_message
from coding.web.ws.serializer import serialize_event, serialize_message

logger = logging.getLogger(__name__)

# Settings keys
_KEY_WORKSPACE = "workspace"
_KEY_ENDPOINT = "endpoint"
_KEY_DISCOVERED = "discovered_models"
_KEY_LAST_MODEL = "last_model"
_KEY_APPROVAL_MODE = "approval_mode"

# API id used for every model (OpenAI-compatible only).
_API_ID = "openai-completions"

# Provider id used for user-supplied OpenAI-compatible endpoints.
_CUSTOM_PROVIDER = "custom"

# Stand-ins for endpoints that do not report context/output limits.
_DEFAULT_CONTEXT_WINDOW = 128000
_DEFAULT_MAX_TOKENS = 8192

# The OpenAI SDK needs a non-empty key even for endpoints without auth.
_PLACEHOLDER_KEY = "none"


class AgentManager:
    """Manages an AgentSession instance for a single WebSocket connection."""

    def __init__(self, db: Database, default_workspace: str = "", agent_dir: str = "") -> None:
        self._db = db
        self._sessions = SessionStore(db)
        self._settings = SettingsStore(db)
        self._keys = ProviderKeyStore(db)
        self._default_workspace = default_workspace or os.getcwd()
        self._agent_dir = agent_dir or os.path.expanduser("~/.coding")

        self._session: AgentSession | None = None
        self._registry: ModelRegistry = ModelRegistry(agent_dir=self._agent_dir)
        self._session_id: str = ""
        self._workspace: str = self._default_workspace
        self._endpoint: dict[str, Any] | None = None
        self._base_urls: dict[str, str] = {}
        # Models fetched from an endpoint's ``/models`` listing, per provider.
        self._discovered: dict[str, list[str]] = {}
        # The model the user last selected, as ``{"provider", "id"}``.
        self._last_model: dict[str, str] | None = None
        self._unsubscribe: Any = None
        self._send: Any = None  # async callable to send JSON to WebSocket
        # Tool approval: mode plus the calls currently waiting on the browser.
        self._approval_mode: ApprovalMode = DEFAULT_APPROVAL_MODE
        self._pending_approvals: dict[str, asyncio.Future[ToolApprovalDecision]] = {}
        self._run_task: asyncio.Task[None] | None = None

    # --- Properties ---

    @property
    def session(self) -> AgentSession | None:
        return self._session

    @property
    def agent(self) -> Agent | None:
        return self._session.agent if self._session else None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def is_running(self) -> bool:
        """True while an agent run is in flight."""
        return self._run_task is not None and not self._run_task.done()

    @property
    def approval_mode(self) -> ApprovalMode:
        return self._approval_mode

    def set_send(self, send_fn: Any) -> None:
        """Set the async send function for WebSocket output."""
        self._send = send_fn

    async def _send_json(self, data: dict[str, Any]) -> None:
        if self._send:
            await self._send(data)

    # --- Registry / preferences ---

    def _build_registry(self) -> ModelRegistry:
        """Build the model registry from built-ins plus a custom endpoint."""
        registry = ModelRegistry(agent_dir=self._agent_dir)
        for provider_name in get_providers():
            for model in get_models(provider_name):
                registry.register(model)

        endpoint = self._endpoint
        if endpoint and endpoint.get("baseUrl") and endpoint.get("models"):
            registry.register_provider(
                endpoint.get("provider", "custom"),
                base_url=endpoint["baseUrl"],
                api=_API_ID,
                models=endpoint["models"],
            )

        # Apply per-provider base URL overrides entered alongside the API key.
        for provider, base_url in self._base_urls.items():
            if not base_url:
                continue
            for model in list(registry.get_models_for_provider(provider)):
                registry.register(model.model_copy(update={"base_url": base_url}))

        self._register_discovered_models(registry)
        return registry

    def _register_discovered_models(self, registry: ModelRegistry) -> None:
        """Register models fetched from an endpoint's ``/models`` listing.

        Built-in definitions win where the IDs match: they carry the reasoning,
        cost and context-window metadata that ``/models`` does not report.

        ``compat`` is set explicitly: ``/models`` says nothing about which
        request fields an endpoint tolerates, and the provider name (``custom``
        or a preset id we do not own) never matches ``_detect_compat``, so
        without this we would send OpenAI-only fields to a stranger's server.
        """
        for provider, model_ids in self._discovered.items():
            base_url = self._effective_base_url(provider)
            if not base_url:
                continue
            for model_id in model_ids:
                if not model_id or registry.find(provider, model_id) is not None:
                    continue
                registry.register(
                    Model(
                        id=model_id,
                        name=model_id,
                        api=_API_ID,
                        provider=provider,
                        baseUrl=base_url,
                        input=["text"],
                        contextWindow=_DEFAULT_CONTEXT_WINDOW,
                        maxTokens=_DEFAULT_MAX_TOKENS,
                        compat=THIRD_PARTY_COMPAT,
                    )
                )

    def _effective_base_url(self, provider: str) -> str:
        """Get the endpoint a provider's models should be sent to."""
        override = self._base_urls.get(provider)
        if override:
            return override
        preset = get_vendor_preset(provider)
        if preset is not None:
            return preset.base_url
        endpoint = self._endpoint
        if endpoint and endpoint.get("provider", _CUSTOM_PROVIDER) == provider:
            return endpoint.get("baseUrl", "")
        return ""

    async def load_preferences(self) -> None:
        """Load persisted workspace/endpoint preferences."""
        workspace = await self._settings.get(_KEY_WORKSPACE)
        if isinstance(workspace, str) and workspace:
            self._workspace = workspace

        endpoint = await self._settings.get(_KEY_ENDPOINT)
        if isinstance(endpoint, dict):
            self._endpoint = endpoint

        self._base_urls = await self._keys.get_base_urls()

        discovered = await self._settings.get(_KEY_DISCOVERED)
        if isinstance(discovered, dict):
            self._discovered = {
                provider: [str(model_id) for model_id in model_ids]
                for provider, model_ids in discovered.items()
                if isinstance(model_ids, list)
            }

        last_model = await self._settings.get(_KEY_LAST_MODEL)
        if isinstance(last_model, dict):
            self._last_model = {
                "provider": str(last_model.get("provider", "")),
                "id": str(last_model.get("id", "")),
            }

        approval_mode = await self._settings.get(_KEY_APPROVAL_MODE)
        if isinstance(approval_mode, str) and approval_mode in VALID_APPROVAL_MODES:
            self._approval_mode = approval_mode

        self._registry = self._build_registry()

    async def _default_model(self) -> Model | None:
        """Pick a sensible default model.

        The model the user last chose wins. Falling back to "first provider
        with a key on file" is not good enough: registration order decides it,
        and a key that no longer works -- or that was filed under the wrong
        provider -- would quietly put every new chat back on a model that
        cannot answer.
        """
        if self._last_model is not None:
            remembered = self._registry.find(
                self._last_model.get("provider", ""), self._last_model.get("id", "")
            )
            if remembered is not None:
                return remembered

        models = self._registry.get_all()
        if not models:
            return None
        for model in models:
            if await self._has_key(model.provider):
                return model
        return models[0]

    async def _remember_model(self, model: Model) -> None:
        """Persist the active model so later sessions start on it."""
        self._last_model = {"provider": model.provider, "id": model.id}
        await self._settings.set(_KEY_LAST_MODEL, self._last_model)

    async def _has_key(self, provider: str) -> bool:
        return await self._keys.exists(provider) or bool(get_env_api_key(provider))

    # --- Session lifecycle ---

    async def new_session(self) -> str:
        """Create a new session with a fresh agent session."""
        await self.load_preferences()
        session_id = str(uuid.uuid4())
        self._session_id = session_id

        self._dispose_session()

        model = await self._default_model()
        self._session = self._create_session(model=model, messages=[], thinking_level="off")
        return session_id

    async def load_session(self, session_id: str) -> bool:
        """Load an existing session from storage."""
        data = await self._sessions.load(session_id)
        if data is None:
            return False

        await self.load_preferences()
        self._session_id = session_id
        self._dispose_session()

        model = None
        try:
            model_data = json.loads(data["model_json"])
            if model_data:
                model = Model.model_validate(model_data)
        except Exception:
            logger.exception("Failed to deserialize model for session %s", session_id)

        # Ensure the stored model still exists in the registry; fall back if not.
        if model is not None and self._registry.find(model.provider, model.id) is None:
            model = self._registry.find(model.provider, model.id) or await self._default_model()

        thinking_level: ThinkingLevel = data.get("thinking_level", "off")  # type: ignore[assignment]

        messages: list[Any] = []
        try:
            raw = json.loads(data["messages_json"])
            from coding.ai.types import AssistantMessage, ToolResultMessage, UserMessage

            for m in raw:
                role = m.get("role", "")
                if role == "user":
                    messages.append(UserMessage.model_validate(m))
                elif role == "assistant":
                    messages.append(AssistantMessage.model_validate(m))
                elif role in ("tool_result", "toolResult"):
                    messages.append(ToolResultMessage.model_validate(m))
        except Exception:
            logger.exception("Failed to deserialize messages for session %s", session_id)

        self._session = self._create_session(model=model, messages=messages, thinking_level=thinking_level)
        return True

    def _create_session(
        self,
        *,
        model: Model | None,
        messages: list[Any],
        thinking_level: ThinkingLevel,
    ) -> AgentSession:
        """Create an AgentSession with coding tools rooted at the workspace."""
        agent = Agent(
            initial_state=AgentState(
                model=model,
                thinking_level=thinking_level,
                messages=messages,
            ),
            get_api_key=self._get_api_key,
            session_id=self._session_id,
        )

        session = AgentSession(
            AgentSessionConfig(
                agent=agent,
                session_manager=SessionManager.in_memory(self._workspace),
                settings_manager=SettingsManager.in_memory(),
                cwd=self._workspace,
                model_registry=self._registry,
                approval_mode=self._approval_mode,
                approval_handler=self._request_tool_approval,
            )
        )
        self._unsubscribe = session.subscribe(self._on_event)
        return session

    def _dispose_session(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        self._session = None

    async def save_session(self) -> None:
        """Save current session state to storage."""
        agent = self.agent
        if agent is None or not self._session_id:
            return

        state = agent.state
        model_json = state.model.model_dump_json(by_alias=True) if state.model else "{}"
        messages_data = []
        for msg in state.messages:
            if hasattr(msg, "model_dump"):
                messages_data.append(msg.model_dump(by_alias=True))
        messages_json = json.dumps(messages_data)

        title = SessionStore.extract_title(messages_json)
        preview = SessionStore.extract_preview(messages_json)

        await self._sessions.save(
            self._session_id,
            model_json=model_json,
            thinking_level=state.thinking_level,
            messages_json=messages_json,
            title=title,
            message_count=len(state.messages),
            model_id=state.model.id if state.model else "",
            preview=preview,
        )

    # --- Agent operations ---

    def start_prompt(self, text: str) -> None:
        """Run a prompt in the background so the socket keeps reading messages.

        Waiting inside the read loop would block every other message, including
        an abort or an approval reply, until the whole run finished.
        """
        self._run_task = asyncio.create_task(self.prompt(text))

    async def prompt(self, text: str) -> None:
        """Send a user prompt to the agent."""
        if self._session is None:
            await self._send_json({"type": "error", "message": "No active session"})
            return

        model = self._session.agent.state.model
        if model is None:
            await self._send_json({"type": "error", "message": "No model selected"})
            return

        if not await self._has_key(model.provider):
            await self._send_json({"type": "api_key_required", "provider": model.provider})
            return

        try:
            await self._session.prompt(text)
        except Exception as e:
            logger.exception("Error during prompt")
            await self._send_json({"type": "error", "message": str(e)})
        finally:
            await self._persist_session()

    def abort(self) -> None:
        """Abort the current agent run."""
        if self._session:
            self._session.abort()
        self.deny_pending_approvals("Aborted by user")

    # --- Tool approval ---

    async def set_approval_mode(self, mode: str) -> None:
        """Switch between automatic execution and asking for consent."""
        if mode not in VALID_APPROVAL_MODES:
            await self._send_json({"type": "error", "message": f"Unknown approval mode: {mode}"})
            return
        self._approval_mode = cast("ApprovalMode", mode)
        if self._session:
            self._session.set_approval_mode(mode)
        await self._settings.set(_KEY_APPROVAL_MODE, mode)

    async def _request_tool_approval(self, request: ToolApprovalRequest, reason: str) -> ToolApprovalDecision:
        """Ask the browser to approve one tool call, then wait for its answer."""
        if self._send is None or self._session is None:
            return ToolApprovalDecision(approved=False, reason="No client is connected to approve this call")
        if request.tool_call_id in self._pending_approvals:
            return ToolApprovalDecision(approved=False, reason="Duplicate approval request")

        future: asyncio.Future[ToolApprovalDecision] = asyncio.get_running_loop().create_future()
        self._pending_approvals[request.tool_call_id] = future
        try:
            # Send before awaiting: the browser can only answer what it has seen.
            await self._send_json(
                tool_approval_request_message(request.tool_call_id, request.tool_name, request.args, reason)
            )
            return await future
        finally:
            self._pending_approvals.pop(request.tool_call_id, None)

    def resolve_approval(self, tool_call_id: str, approved: bool, always_allow_tool: bool, reason: str) -> bool:
        """Deliver the user's answer to a tool call that is waiting for one."""
        future = self._pending_approvals.get(tool_call_id)
        if future is None or future.done():
            return False
        future.set_result(
            ToolApprovalDecision(approved=approved, always_allow_tool=always_allow_tool, reason=reason)
        )
        return True

    def deny_pending_approvals(self, reason: str) -> None:
        """Refuse every waiting tool call so no run stays suspended forever."""
        for future in list(self._pending_approvals.values()):
            if not future.done():
                future.set_result(ToolApprovalDecision(approved=False, reason=reason))

    async def set_model(self, provider: str, model_id: str) -> None:
        """Set the agent's model."""
        model = self._registry.find(provider, model_id)
        if model and self._session:
            await self._session.set_model(model)
            await self._remember_model(model)

    def set_thinking_level(self, level: str) -> None:
        """Set the agent's thinking level."""
        if self._session and level in ("off", "minimal", "low", "medium", "high", "xhigh"):
            self._session.set_thinking_level(level)

    async def set_workspace(self, path: str) -> bool:
        """Change the workspace directory and rebuild the tools/system prompt."""
        resolved = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(resolved):
            await self._send_json({"type": "error", "message": f"Not a directory: {path}"})
            return False

        self._workspace = resolved
        await self._settings.set(_KEY_WORKSPACE, resolved)

        if self._session is not None:
            agent = self._session.agent
            messages = list(agent.state.messages)
            model = agent.state.model
            thinking = agent.state.thinking_level
            self._dispose_session()
            self._session = self._create_session(model=model, messages=messages, thinking_level=thinking)
        return True

    async def set_endpoint(
        self,
        *,
        provider: str,
        base_url: str,
        model_ids: list[str],
        api_key: str = "",
    ) -> None:
        """Configure a custom OpenAI-compatible endpoint."""
        provider = provider or "custom"
        models = [
            {"id": mid, "name": mid, "contextWindow": 128000, "maxTokens": 8192}
            for mid in model_ids
            if mid
        ]
        self._endpoint = {"provider": provider, "baseUrl": base_url, "models": models}
        await self._settings.set(_KEY_ENDPOINT, self._endpoint)
        if api_key:
            await self._keys.set(provider, api_key)
        self._registry = self._build_registry()

    async def set_api_key(self, provider: str, key: str, base_url: str = "") -> None:
        """Store an API key and optional base URL override for a provider.

        Also refreshes the provider's model list from its ``/models`` endpoint
        on a best-effort basis: a provider that does not expose one keeps the
        built-in model definitions.
        """
        await self._keys.set(provider, key, base_url)
        await self._refresh_discovered_models(provider)
        await self._apply_key_change(provider)

    async def set_custom_endpoint(self, base_url: str, key: str = "") -> bool:
        """Configure a custom OpenAI-compatible endpoint and its models.

        The model list is mandatory here -- without it there is nothing to
        select -- so failures are reported to the client and return False.
        """
        base_url = (base_url or "").strip()
        if not base_url:
            await self._send_json({"type": "error", "message": "Base URL is required"})
            return False

        try:
            model_ids = await discover_model_ids(base_url, key)
        except ModelDiscoveryError as e:
            await self._send_json({"type": "error", "message": str(e)})
            return False

        if not model_ids:
            await self._send_json({"type": "error", "message": f"No models found at {base_url}"})
            return False

        await self._keys.set(_CUSTOM_PROVIDER, key, base_url)
        self._discovered[_CUSTOM_PROVIDER] = model_ids
        await self._save_discovered()
        await self._apply_key_change(_CUSTOM_PROVIDER)
        return True

    async def _refresh_discovered_models(self, provider: str) -> None:
        """Refresh a provider's stored model list from its endpoint."""
        base_url = self._effective_base_url(provider)
        if not base_url:
            return

        key = await self._keys.get(provider) or get_env_api_key(provider) or ""
        try:
            model_ids = await discover_model_ids(base_url, key)
        except ModelDiscoveryError:
            logger.info("Keeping built-in models for %s: discovery failed", provider)
            return

        if model_ids:
            self._discovered[provider] = model_ids
            await self._save_discovered()

    async def _save_discovered(self) -> None:
        await self._settings.set(_KEY_DISCOVERED, self._discovered)

    async def _apply_key_change(self, provider: str) -> None:
        """Make a freshly configured provider usable without a reload."""
        self._base_urls = await self._keys.get_base_urls()
        self._registry = self._build_registry()
        await self._switch_to_provider_model(provider)
        self._refresh_active_model()

    async def _switch_to_provider_model(self, provider: str) -> None:
        """Point the session at the just-configured provider.

        Configuring a provider is the user saying they want to use it, so the
        active model follows -- including when the provider being left behind
        still has a key stored. Deferring to that key strands the user: keys
        outlive the provider they are filed under, so a key entered before the
        vendor picker existed sits under ``openai`` whatever it really is, and
        the model it belongs to then cannot answer.
        """
        if self._session is None:
            return

        current = self._session.agent.state.model
        if current is not None and current.provider == provider:
            return

        model = self._default_model_for(provider)
        if model is not None:
            await self._session.set_model(model)
            await self._remember_model(model)

    def _default_model_for(self, provider: str) -> Model | None:
        models = self._registry.get_models_for_provider(provider)
        return models[0] if models else None

    async def delete_api_key(self, provider: str) -> None:
        """Delete an API key for a provider."""
        await self._keys.delete(provider)
        self._discovered.pop(provider, None)
        await self._save_discovered()
        self._base_urls = await self._keys.get_base_urls()
        self._registry = self._build_registry()
        self._refresh_active_model()

    def _refresh_active_model(self) -> None:
        """Re-resolve the active model so registry changes take effect immediately."""
        if self._session is None:
            return
        current = self._session.agent.state.model
        if current is None:
            return
        updated = self._registry.find(current.provider, current.id)
        if updated is not None:
            self._session.agent.state.model = updated

    async def delete_session(self, session_id: str) -> None:
        """Delete a session from storage."""
        await self._sessions.delete(session_id)

    # --- State serialization ---

    def get_state_dict(self) -> dict[str, Any]:
        """Get full state for sending to client."""
        if self._session is None:
            return {
                "type": "state",
                "sessionId": self._session_id,
                "model": None,
                "thinkingLevel": "off",
                "messages": [],
                "isStreaming": False,
                "workspace": self._workspace,
                "endpoint": self._endpoint,
                "approvalMode": self._approval_mode,
            }

        state = self._session.agent.state
        model_dict = state.model.model_dump(by_alias=True) if state.model else None
        messages = [serialize_message(m) for m in state.messages]

        return {
            "type": "state",
            "sessionId": self._session_id,
            "model": model_dict,
            "thinkingLevel": state.thinking_level,
            "messages": messages,
            "isStreaming": state.is_streaming,
            "workspace": self._workspace,
            "endpoint": self._endpoint,
            "tools": self._session.get_active_tool_names(),
            "approvalMode": self._approval_mode,
        }

    async def get_models_dict(self) -> dict[str, Any]:
        """Get available models grouped by provider."""
        provider_list = []
        seen: set[str] = set()
        for model in self._registry.get_all():
            if model.provider in seen:
                continue
            seen.add(model.provider)
            provider_list.append(
                {
                    "name": model.provider,
                    "models": [
                        m.model_dump(by_alias=True)
                        for m in self._registry.get_models_for_provider(model.provider)
                    ],
                }
            )
        return {
            "type": "models",
            "providers": provider_list,
            "baseUrls": dict(self._base_urls),
            "vendors": get_vendor_presets(),
            "configuredProviders": sorted((await self._keys.get_all()).keys()),
        }

    async def get_sessions_dict(self) -> dict[str, Any]:
        """Get all session metadata."""
        metadata = await self._sessions.get_all_metadata()
        return {"type": "sessions", "sessions": metadata}

    # --- Private ---

    async def _get_api_key(self, provider: str) -> str | None:
        """Callback for the Agent to retrieve API keys."""
        key = await self._keys.get(provider)
        if key:
            return key
        env_key = get_env_api_key(provider)
        if env_key:
            return env_key
        # Keyless endpoints (local servers) still need a non-empty placeholder.
        if await self._keys.exists(provider):
            return _PLACEHOLDER_KEY
        return None

    def _on_event(self, event: AgentEvent) -> None:
        """Forward agent events to the WebSocket."""
        data = serialize_event(event)
        if data and self._send:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._send_json(data))
            except RuntimeError:
                pass

    async def _persist_session(self) -> None:
        """Persist the session, surviving cancellation of the run that triggered it.

        A client that disconnects the moment a run ends cancels that run, and the
        cancellation lands on the first await inside save_session, so the write
        never happens and nothing anywhere reports it. Shielding the write means
        the conversation still reaches the sidebar.
        """
        write = asyncio.create_task(self.save_session())
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            with suppress(Exception):
                await write
            raise

    async def cleanup(self) -> None:
        """Clean up when WebSocket disconnects."""
        # Unblock anything waiting on the browser before tearing the session down.
        self.deny_pending_approvals("Client disconnected")
        if self._session and self._session.agent.state.is_streaming:
            self._session.abort()
        if self._run_task is not None and not self._run_task.done():
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
        self._run_task = None
        # Save before disposing: _dispose_session() clears the agent that
        # save_session() reads from, so saving afterwards is a silent no-op and
        # the session never appears in the sidebar.
        await self._persist_session()
        self._dispose_session()

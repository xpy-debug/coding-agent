"""WebSocket endpoint handler."""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from coding.web.agent_manager import AgentManager
from coding.web.storage.database import Database
from coding.web.ws.protocol import (
    AbortMessage,
    DeleteApiKeyMessage,
    DeleteSessionMessage,
    LoadSessionMessage,
    NewSessionMessage,
    PromptMessage,
    SetApiKeyMessage,
    SetApprovalModeMessage,
    SetCustomEndpointMessage,
    SetModelMessage,
    SetThinkingLevelMessage,
    ToolApprovalReplyMessage,
    parse_client_message,
)

logger = logging.getLogger(__name__)


async def websocket_handler(websocket: WebSocket, db: Database) -> None:
    """Main WebSocket handler - one per client connection."""
    await websocket.accept()

    manager = AgentManager(db)

    async def send_json(data: dict[str, Any]) -> None:
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    manager.set_send(send_json)

    # Create initial session
    await manager.new_session()

    # Send initial state + models + sessions
    await send_json(manager.get_state_dict())
    await send_json(await manager.get_models_dict())
    await send_json(await manager.get_sessions_dict())

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg = parse_client_message(data)
            if msg is None:
                await send_json({"type": "error", "message": f"Unknown message type: {data.get('type')}"})
                continue

            match msg:
                case PromptMessage():
                    if manager.is_running:
                        await send_json({"type": "error", "message": "Agent is already running"})
                    else:
                        # Backgrounded so this loop keeps reading: an abort or an
                        # approval reply has to get through while the agent runs.
                        manager.start_prompt(msg.text)

                case AbortMessage():
                    manager.abort()

                case ToolApprovalReplyMessage():
                    resolved = manager.resolve_approval(
                        msg.tool_call_id, msg.approved, msg.always_allow_tool, msg.reason
                    )
                    if not resolved:
                        await send_json({"type": "error", "message": "No pending approval for this tool call"})

                case SetApprovalModeMessage():
                    await manager.set_approval_mode(msg.mode)
                    await send_json(manager.get_state_dict())

                case SetModelMessage():
                    await manager.set_model(msg.provider, msg.model_id)
                    await send_json(manager.get_state_dict())

                case SetThinkingLevelMessage():
                    manager.set_thinking_level(msg.level)
                    await send_json(manager.get_state_dict())

                case LoadSessionMessage():
                    if manager.is_running:
                        await send_json({"type": "error", "message": "Abort the current run first"})
                    else:
                        loaded = await manager.load_session(msg.session_id)
                        if loaded:
                            await send_json(manager.get_state_dict())
                        else:
                            await send_json({"type": "error", "message": "Session not found"})

                case NewSessionMessage():
                    if manager.is_running:
                        await send_json({"type": "error", "message": "Abort the current run first"})
                    else:
                        await manager.save_session()
                        await manager.new_session()
                        await send_json(manager.get_state_dict())
                        await send_json(await manager.get_sessions_dict())

                case SetApiKeyMessage():
                    await manager.set_api_key(msg.provider, msg.key, msg.base_url)
                    await send_json(
                        {
                            "type": "api_key_saved",
                            "provider": msg.provider,
                            "baseUrl": msg.base_url,
                        }
                    )
                    await send_json(await manager.get_models_dict())
                    await send_json(manager.get_state_dict())

                case SetCustomEndpointMessage():
                    # The manager reports its own errors, so only announce
                    # success.
                    if await manager.set_custom_endpoint(msg.base_url, msg.key):
                        await send_json(
                            {
                                "type": "api_key_saved",
                                "provider": "custom",
                                "baseUrl": msg.base_url,
                            }
                        )
                        await send_json(await manager.get_models_dict())
                        await send_json(manager.get_state_dict())

                case DeleteSessionMessage():
                    await manager.delete_session(msg.session_id)
                    await send_json(await manager.get_sessions_dict())

                case DeleteApiKeyMessage():
                    await manager.delete_api_key(msg.provider)
                    await send_json(await manager.get_models_dict())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        await manager.cleanup()

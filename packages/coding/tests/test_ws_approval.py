"""End-to-end test for the tool approval round-trip over the WebSocket.

Drives the real FastAPI app, websocket handler, AgentManager, AgentSession,
agent loop, approval policy and the real bash tool. Only the model is faked:
it asks for four bash commands in a row, then answers with text.

The run suspends on the server while it waits for an answer, so this also pins
down that the handler keeps reading the socket during a run -- the reply could
not get through otherwise, and the run would hang forever.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.testclient import TestClient

import coding.web.agent_manager as agent_manager_module
from coding.ai.events import AssistantMessageEventStream
from coding.ai.types import AssistantMessage, DoneEvent, StartEvent, TextContent, ToolCall
from coding.web.app import create_app
from coding.web.config import Config

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch

COMMANDS = [
    "echo probed",
    "echo nope > {denied}",  # denied: must never run
    "echo allowed-again",  # approved with "always allow bash"
    "echo no-ask",  # allowlisted: must not be asked about
]


def _make_stream_fn(commands: list[str]):
    """Fake model: one bash tool call per command, then a text answer."""
    counter = {"n": 0}

    def stream_fn(model, context, options=None):
        stream = AssistantMessageEventStream()
        model_id = getattr(model, "id", "probe")
        index = counter["n"]
        counter["n"] += 1

        if index < len(commands):
            message = AssistantMessage(
                content=[ToolCall(id=f"probe_call_{index}", name="bash", arguments={"command": commands[index]})],
                model=model_id,
                stop_reason="tool_use",
                timestamp=index + 1,
            )
            stream.push(StartEvent(partial=message))
            stream.push(DoneEvent(reason="tool_use", message=message))
        else:
            message = AssistantMessage(
                content=[TextContent(text="all done")], model=model_id, timestamp=index + 1
            )
            stream.push(StartEvent(partial=message))
            stream.push(DoneEvent(reason="stop", message=message))
        return stream

    return stream_fn


def _result_text(message: dict) -> str:
    result = message.get("result") or {}
    return "".join(
        block.get("text", "") for block in result.get("content", []) if block.get("type") == "text"
    )


def test_approval_round_trip_over_the_socket(tmp_path: Path, monkeypatch: MonkeyPatch):
    denied_file = tmp_path / "denied_probe.txt"
    commands = [command.format(denied=denied_file.as_posix()) for command in COMMANDS]

    # The prompt path needs a key on file before it will start a run.
    monkeypatch.setattr(agent_manager_module, "get_env_api_key", lambda provider: "probe-key")

    original_create_session = agent_manager_module.AgentManager._create_session

    def patched_create_session(self, **kwargs):
        session = original_create_session(self, **kwargs)
        session.agent.stream_fn = _make_stream_fn(commands)
        return session

    monkeypatch.setattr(agent_manager_module.AgentManager, "_create_session", patched_create_session)

    app = create_app(Config(db_path=str(tmp_path / "probe.db"), workspace=str(tmp_path)))
    transcript: list[dict] = []

    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "set_approval_mode", "mode": "ask"})
        ws.send_json({"type": "prompt", "text": "run the probe commands"})

        for _ in range(400):
            data = ws.receive_json()
            transcript.append(data)
            kind = data.get("type")

            if kind == "tool_approval_request":
                command = (data.get("args") or {}).get("command", "")
                reply = {"type": "tool_approval_reply", "toolCallId": data["toolCallId"], "approved": True}
                if command.startswith("echo nope"):
                    reply["approved"] = False
                    reply["reason"] = "probe denial"
                elif command.startswith("echo allowed-again"):
                    reply["alwaysAllowTool"] = True
                ws.send_json(reply)
            elif kind == "agent_end":
                break

    requests = [m for m in transcript if m.get("type") == "tool_approval_request"]
    asked = [(m.get("args") or {}).get("command") for m in requests]
    tool_ends = {m.get("toolCallId"): m for m in transcript if m.get("type") == "tool_end"}
    errors = [m for m in transcript if m.get("type") == "error"]
    states = [m for m in transcript if m.get("type") == "state"]

    # The run must finish: it was suspended waiting for answers.
    assert transcript[-1].get("type") == "agent_end", transcript[-1]
    assert not errors, errors

    # The mode switch reached the running session.
    assert states[-1]["approvalMode"] == "ask"

    # Asked about the three gated calls, and not about the allowlisted one.
    assert asked == commands[:3], asked

    # Every executed call reported a result frame (these used to be dropped
    # because the tool details were not JSON-serializable).
    assert set(tool_ends) == {f"probe_call_{index}" for index in range(len(commands))}, sorted(tool_ends)

    # Approved call ran, with real command output.
    assert tool_ends["probe_call_0"]["isError"] is False
    assert "probed" in _result_text(tool_ends["probe_call_0"])

    # Each executed call reports how long it took; a denied call reports nothing.
    tool_messages = [
        m["message"]
        for m in transcript
        if m.get("type") == "message_end" and (m.get("message") or {}).get("toolCallId")
    ]
    durations = {message["toolCallId"]: message.get("durationMs") for message in tool_messages}
    assert durations["probe_call_0"] is not None and durations["probe_call_0"] >= 0
    assert durations["probe_call_1"] is None

    # Denied call never ran and told the model why.
    assert tool_ends["probe_call_1"]["isError"] is True
    assert not denied_file.exists()
    assert "denied" in _result_text(tool_ends["probe_call_1"]).lower()

    # "Always allow bash" took effect for the rest of the session.
    assert tool_ends["probe_call_2"]["isError"] is False
    assert tool_ends["probe_call_3"]["isError"] is False
    assert [m.get("toolCallId") for m in requests] == ["probe_call_0", "probe_call_1", "probe_call_2"]

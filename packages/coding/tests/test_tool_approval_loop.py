"""Tests for the human-in-the-loop approval gate in the agent loop."""

from __future__ import annotations

import asyncio

from coding.agent.loop import _execute_tool_calls, agent_loop
from coding.agent.types import (
    AgentContext,
    AgentEndEvent,
    AgentLoopConfig,
    AgentTool,
    AgentToolResult,
    ToolApprovalDecision,
    ToolApprovalRequest,
)
from coding.ai.types import AssistantMessage, TextContent, ToolCall, UserMessage


class _RecordingStream:
    """Stands in for the agent event stream, keeping every pushed event."""

    def __init__(self) -> None:
        self.events: list = []

    def push(self, event) -> None:
        self.events.append(event)

    @property
    def event_names(self) -> list[str]:
        return [type(event).__name__ for event in self.events]


def _assistant_message(*tool_calls: ToolCall) -> AssistantMessage:
    return AssistantMessage(content=list(tool_calls), model="test-model", timestamp=1)


def _tool(name: str, executed: list) -> AgentTool:
    async def execute(tool_call_id, params, cancel_event=None, on_update=None):
        executed.append((tool_call_id, params))
        return AgentToolResult(content=[TextContent(text="ran")])

    return AgentTool(name=name, description="", parameters={"type": "object"}, execute=execute)


async def test_denied_call_never_executes():
    executed: list = []
    stream = _RecordingStream()

    async def deny(request: ToolApprovalRequest) -> ToolApprovalDecision:
        return ToolApprovalDecision(approved=False, reason="not on my watch")

    outcome = await _execute_tool_calls(
        [_tool("bash", executed)],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={"command": "rm -rf /"})),
        None,
        stream,
        None,
        deny,
    )

    assert executed == []
    assert stream.event_names == [
        "ToolExecutionStartEvent",
        "ToolExecutionEndEvent",
        "MessageStartEvent",
        "MessageEndEvent",
    ]
    assert stream.events[1].is_error is True

    result = outcome["tool_results"][0]
    assert result.is_error is True
    assert result.tool_call_id == "call_1"
    assert "User denied execution of bash" in result.content[0].text
    assert result.details.type == "denied"
    # Nothing ran, so there is no execution time to report.
    assert result.duration_ms is None


async def test_approved_call_runs_like_the_ungated_path():
    executed: list = []
    stream = _RecordingStream()

    async def approve(request: ToolApprovalRequest) -> ToolApprovalDecision:
        return ToolApprovalDecision(approved=True)

    outcome = await _execute_tool_calls(
        [_tool("bash", executed)],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={"command": "echo hi"})),
        None,
        stream,
        None,
        approve,
    )

    assert executed == [("call_1", {"command": "echo hi"})]
    assert outcome["tool_results"][0].is_error is False
    assert outcome["tool_results"][0].duration_ms is not None
    assert stream.event_names == [
        "ToolExecutionStartEvent",
        "ToolExecutionEndEvent",
        "MessageStartEvent",
        "MessageEndEvent",
    ]


async def test_duration_measures_the_execution_time():
    stream = _RecordingStream()

    async def slow_tool(tool_call_id, params, cancel_event=None, on_update=None):
        await asyncio.sleep(0.05)
        return AgentToolResult(content=[TextContent(text="ran")])

    async def approve(request: ToolApprovalRequest) -> ToolApprovalDecision:
        return ToolApprovalDecision(approved=True)

    tool = AgentTool(name="bash", description="", parameters={"type": "object"}, execute=slow_tool)
    outcome = await _execute_tool_calls(
        [tool],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={})),
        None,
        stream,
        None,
        approve,
    )

    assert outcome["tool_results"][0].duration_ms >= 40


async def test_approval_wait_is_not_counted_as_execution_time():
    """Time spent waiting for a human is not tool execution time."""
    stream = _RecordingStream()

    async def instant_tool(tool_call_id, params, cancel_event=None, on_update=None):
        return AgentToolResult(content=[TextContent(text="ran")])

    async def slow_approval(request: ToolApprovalRequest) -> ToolApprovalDecision:
        await asyncio.sleep(0.05)
        return ToolApprovalDecision(approved=True)

    tool = AgentTool(name="bash", description="", parameters={"type": "object"}, execute=instant_tool)
    outcome = await _execute_tool_calls(
        [tool],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={})),
        None,
        stream,
        None,
        slow_approval,
    )

    assert outcome["tool_results"][0].duration_ms < 40


async def test_without_a_callback_tools_run_ungated():
    executed: list = []
    stream = _RecordingStream()

    outcome = await _execute_tool_calls(
        [_tool("bash", executed)],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={"command": "echo hi"})),
        None,
        stream,
        None,
    )

    assert executed == [("call_1", {"command": "echo hi"})]
    assert outcome["tool_results"][0].is_error is False


async def test_callback_is_asked_once_per_tool_call():
    asked: list[str] = []
    executed: list = []
    stream = _RecordingStream()

    async def approve(request: ToolApprovalRequest) -> ToolApprovalDecision:
        asked.append(request.tool_call_id)
        return ToolApprovalDecision(approved=True)

    await _execute_tool_calls(
        [_tool("bash", executed), _tool("read", executed)],
        _assistant_message(
            ToolCall(id="call_1", name="bash", arguments={}),
            ToolCall(id="call_2", name="read", arguments={}),
        ),
        None,
        stream,
        None,
        approve,
    )

    assert asked == ["call_1", "call_2"]


async def test_cancel_while_waiting_denies_and_skips_the_rest():
    executed: list = []
    stream = _RecordingStream()
    cancel_event = asyncio.Event()

    async def never_answers(request: ToolApprovalRequest) -> ToolApprovalDecision:
        cancel_event.set()  # the user hit stop with the prompt still open
        await asyncio.sleep(60)
        return ToolApprovalDecision(approved=True)

    outcome = await _execute_tool_calls(
        [_tool("bash", executed), _tool("edit", executed)],
        _assistant_message(
            ToolCall(id="call_1", name="bash", arguments={}),
            ToolCall(id="call_2", name="edit", arguments={}),
        ),
        cancel_event,
        stream,
        None,
        never_answers,
    )

    assert executed == []
    assert [result.tool_call_id for result in outcome["tool_results"]] == ["call_1"]
    assert outcome["tool_results"][0].is_error is True
    assert "aborted" in outcome["tool_results"][0].content[0].text.lower()


async def test_a_broken_approver_denies_rather_than_allows():
    executed: list = []
    stream = _RecordingStream()

    async def explode(request: ToolApprovalRequest) -> ToolApprovalDecision:
        raise RuntimeError("approver is broken")

    outcome = await _execute_tool_calls(
        [_tool("bash", executed)],
        _assistant_message(ToolCall(id="call_1", name="bash", arguments={})),
        None,
        stream,
        None,
        explode,
    )

    assert executed == []
    assert outcome["tool_results"][0].is_error is True
    assert "Approval request failed" in outcome["tool_results"][0].content[0].text


async def test_cancelled_run_stops_before_calling_the_model():
    """Abort is honoured at the turn boundary instead of being a no-op."""
    streamed: list = []

    def stream_fn(*args, **kwargs):
        streamed.append(args)
        raise AssertionError("the model must not be called after a cancel")

    cancel_event = asyncio.Event()
    cancel_event.set()

    agent_stream = agent_loop(
        [UserMessage(content="do something", timestamp=1)],
        AgentContext(system_prompt="", messages=[], tools=[]),
        AgentLoopConfig(model=None, convert_to_llm=lambda messages: list(messages)),
        cancel_event,
        stream_fn,
    )

    events = [event async for event in agent_stream]

    assert streamed == []
    assert isinstance(events[-1], AgentEndEvent)


async def test_uncancelled_run_still_streams():
    """Sanity check that the loop still runs when nothing was cancelled."""
    from coding.ai.events import AssistantMessageEventStream
    from coding.ai.types import DoneEvent, StartEvent

    created: list = []

    def stream_fn(*args, **kwargs):
        stream = AssistantMessageEventStream()
        created.append(stream)

        message = AssistantMessage(content=[TextContent(text="hi")], model="test-model", timestamp=1)
        stream.push(StartEvent(partial=message))
        stream.push(DoneEvent(reason="stop", message=message))
        return stream

    agent_stream = agent_loop(
        [UserMessage(content="do something", timestamp=1)],
        AgentContext(system_prompt="", messages=[], tools=[]),
        AgentLoopConfig(model=None, convert_to_llm=lambda messages: list(messages)),
        asyncio.Event(),
        stream_fn,
    )

    events = [event async for event in agent_stream]

    assert created, "the model should have been called"
    assert isinstance(events[-1], AgentEndEvent)

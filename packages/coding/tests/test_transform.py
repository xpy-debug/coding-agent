"""Tests for cross-provider message transformation."""

from coding.ai.providers.transform import transform_messages
from coding.ai.types import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def _user(text: str = "hi", timestamp: int = 1) -> UserMessage:
    return UserMessage(content=[TextContent(text=text)], timestamp=timestamp)


def _assistant(
    content: list[TextContent | ToolCall],
    stop_reason: str = "stop",
    model: str = "test-model",
) -> AssistantMessage:
    return AssistantMessage(content=content, model=model, stop_reason=stop_reason, timestamp=2)


def _tool_result(tool_call_id: str, tool_name: str = "bash") -> ToolResultMessage:
    return ToolResultMessage(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=[TextContent(text="ok")],
        timestamp=3,
    )


def test_orphaned_tool_call_before_user_message_gets_synthetic_result():
    messages = [
        _user(),
        _assistant([ToolCall(id="call_1", name="bash", arguments={})]),
        _user("next"),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result", "user"]
    assert result[2].tool_call_id == "call_1"


def test_trailing_orphaned_tool_call_gets_synthetic_result():
    messages = [
        _user(),
        _assistant([ToolCall(id="call_1", name="bash", arguments={})]),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result"]
    assert result[2].tool_call_id == "call_1"
    assert result[2].tool_name == "bash"


def test_trailing_orphaned_tool_calls_all_get_synthetic_results():
    messages = [
        _user(),
        _assistant(
            [
                ToolCall(id="call_1", name="bash", arguments={}),
                ToolCall(id="call_2", name="read", arguments={}),
                ToolCall(id="call_3", name="edit", arguments={}),
            ]
        ),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result", "tool_result", "tool_result"]
    assert [m.tool_call_id for m in result[2:]] == ["call_1", "call_2", "call_3"]


def test_complete_tool_call_pairs_are_untouched():
    messages = [
        _user(),
        _assistant(
            [
                ToolCall(id="call_1", name="bash", arguments={}),
                ToolCall(id="call_2", name="read", arguments={}),
            ]
        ),
        _tool_result("call_1"),
        _tool_result("call_2", "read"),
        _assistant([TextContent(text="done")]),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result", "tool_result", "assistant"]


def test_orphaned_tool_call_before_skipped_assistant_gets_synthetic_result():
    messages = [
        _user(),
        _assistant([ToolCall(id="call_1", name="bash", arguments={})]),
        _assistant([TextContent(text="")], stop_reason="error"),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result"]


def test_steering_message_between_tool_call_and_result_gets_synthetic_result():
    messages = [
        _user(),
        _assistant([ToolCall(id="call_1", name="bash", arguments={})]),
        _user("stop"),
        _tool_result("call_1"),
    ]

    result = transform_messages(messages)

    assert [m.role for m in result] == ["user", "assistant", "tool_result", "user", "tool_result"]
    assert result[2].tool_call_id == "call_1"


def test_empty_thinking_blocks_are_removed():
    messages = [
        _user(),
        _assistant([ThinkingContent(thinking=""), TextContent(text="answer")]),
    ]

    result = transform_messages(messages)

    assert [b.type for b in result[1].content] == ["text"]

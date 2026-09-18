"""Message transformation for cross-provider compatibility.

Handles tool call ID normalization, thinking block conversion,
and orphaned tool call cleanup.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from coding.ai.types import (
    AssistantMessage,
    Message,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)


def _synthetic_tool_result(tool_call_id: str, tool_name: str, timestamp: int) -> ToolResultMessage:
    """Build a placeholder result for a tool call that never produced one."""
    return ToolResultMessage(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        content=[TextContent(type="text", text="Tool call was interrupted before producing a result.")],
        is_error=False,
        timestamp=timestamp,
    )


def transform_messages(
    messages: list[Message],
    current_model: str | None = None,
    normalize_tool_id: Callable[[str], str] | None = None,
    convert_thinking_to_text: bool = False,
) -> list[Message]:
    """Transform messages for API compatibility.

    - Normalizes tool call IDs if a normalizer is provided
    - Handles thinking blocks (removes empty ones, optionally converts to text)
    - Strips thoughtSignature when switching models
    - Inserts synthetic empty tool results for orphaned tool calls
    - Skips errored/aborted assistant messages
    """
    result: list[Message] = []
    pending_tool_calls: dict[str, str] = {}  # id -> name

    for msg in messages:
        if isinstance(msg, AssistantMessage):
            # Skip errored/aborted messages
            if msg.stop_reason in ("error", "aborted"):
                continue

            msg = deepcopy(msg)
            new_content = []

            for block in msg.content:
                if isinstance(block, ToolCall):
                    # Normalize tool call ID
                    if normalize_tool_id:
                        block.id = normalize_tool_id(block.id)

                    # Strip thought signature when switching models
                    if current_model and msg.model != current_model:
                        block.thought_signature = None

                    pending_tool_calls[block.id] = block.name
                    new_content.append(block)

                elif block.type == "thinking":
                    if convert_thinking_to_text:
                        # Convert thinking blocks to text with delimiters
                        if block.thinking:
                            new_content.append(
                                TextContent(type="text", text=f"<thinking>\n{block.thinking}\n</thinking>")
                            )
                    elif block.thinking or block.thinking_signature:
                        # Keep non-empty thinking blocks or those with signatures
                        new_content.append(block)
                else:
                    new_content.append(block)

            msg.content = new_content
            result.append(msg)

        elif isinstance(msg, ToolResultMessage):
            msg = deepcopy(msg)
            if normalize_tool_id:
                msg.tool_call_id = normalize_tool_id(msg.tool_call_id)
            pending_tool_calls.pop(msg.tool_call_id, None)
            result.append(msg)

        elif isinstance(msg, UserMessage):
            # Insert synthetic results for any orphaned tool calls
            for tc_id, tc_name in pending_tool_calls.items():
                result.append(_synthetic_tool_result(tc_id, tc_name, msg.timestamp))
            pending_tool_calls.clear()
            result.append(msg)
        else:
            result.append(msg)

    # Tool calls still awaiting results when the history ends (e.g. a run that was
    # interrupted after the assistant message was persisted but before its results)
    last_timestamp = result[-1].timestamp if result else 0
    for tc_id, tc_name in pending_tool_calls.items():
        result.append(_synthetic_tool_result(tc_id, tc_name, last_timestamp))

    return result

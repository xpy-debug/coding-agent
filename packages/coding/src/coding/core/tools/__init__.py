"""Coding agent tools: bash, read, write, edit, find, grep, ls."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coding.agent.types import AgentTool
    from coding.core.settings import ToolTimeoutSettings

from coding.core.tools.bash import create_bash_tool
from coding.core.tools.edit import create_edit_tool
from coding.core.tools.find import create_find_tool
from coding.core.tools.grep import create_grep_tool
from coding.core.tools.ls import create_ls_tool
from coding.core.tools.read import create_read_tool
from coding.core.tools.write import create_write_tool


def _tool_timeout(name: str, timeout_settings: ToolTimeoutSettings | None) -> float | None:
    """Resolve the configured timeout (seconds) for a tool name."""
    if timeout_settings is None or timeout_settings.enabled is False:
        return None
    overrides = timeout_settings.overrides or {}
    if name in overrides:
        return float(overrides[name])
    if timeout_settings.default_seconds is not None:
        return float(timeout_settings.default_seconds)
    return None


def create_coding_tools(cwd: str, timeout_settings: ToolTimeoutSettings | None = None) -> list[AgentTool]:
    """Create the standard set of coding tools (read, bash, edit, write)."""
    return [
        create_read_tool(cwd, _tool_timeout("read", timeout_settings)),
        create_bash_tool(cwd, _tool_timeout("bash", timeout_settings)),
        create_edit_tool(cwd, _tool_timeout("edit", timeout_settings)),
        create_write_tool(cwd, _tool_timeout("write", timeout_settings)),
    ]


def create_read_only_tools(cwd: str, timeout_settings: ToolTimeoutSettings | None = None) -> list[AgentTool]:
    """Create read-only exploration tools (read, grep, find, ls)."""
    return [
        create_read_tool(cwd, _tool_timeout("read", timeout_settings)),
        create_grep_tool(cwd, _tool_timeout("grep", timeout_settings)),
        create_find_tool(cwd, _tool_timeout("find", timeout_settings)),
        create_ls_tool(cwd, _tool_timeout("ls", timeout_settings)),
    ]


def create_all_tools(cwd: str, timeout_settings: ToolTimeoutSettings | None = None) -> dict[str, AgentTool]:
    """Create all tools as a dictionary keyed by name."""
    tools = [
        create_read_tool(cwd, _tool_timeout("read", timeout_settings)),
        create_bash_tool(cwd, _tool_timeout("bash", timeout_settings)),
        create_edit_tool(cwd, _tool_timeout("edit", timeout_settings)),
        create_write_tool(cwd, _tool_timeout("write", timeout_settings)),
        create_grep_tool(cwd, _tool_timeout("grep", timeout_settings)),
        create_find_tool(cwd, _tool_timeout("find", timeout_settings)),
        create_ls_tool(cwd, _tool_timeout("ls", timeout_settings)),
    ]
    return {t.name: t for t in tools}


__all__ = [
    "create_all_tools",
    "create_bash_tool",
    "create_coding_tools",
    "create_edit_tool",
    "create_find_tool",
    "create_grep_tool",
    "create_ls_tool",
    "create_read_only_tools",
    "create_read_tool",
    "create_write_tool",
]

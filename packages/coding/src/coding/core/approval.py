"""Human-in-the-loop tool approval policy.

Decides which tool calls need explicit user consent before they run. The
verdict is based on the tool name together with its arguments, so that a
call staying inside the workspace is not interrupted while one reaching
outside it is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from coding.agent.types import ApprovalMode

VALID_APPROVAL_MODES: frozenset[str] = frozenset({"auto", "ask"})
DEFAULT_APPROVAL_MODE: ApprovalMode = "auto"

# Tools that only read state and therefore never need consent.
READ_ONLY_TOOLS: frozenset[str] = frozenset({"read", "ls", "find", "grep"})

# Tools that may touch anything inside the workspace, and nothing outside it.
WORKSPACE_SCOPED_TOOLS: frozenset[str] = frozenset({"write", "edit"})

# Tools that can run arbitrary code, so their arguments cannot be judged.
SHELL_TOOLS: frozenset[str] = frozenset({"bash"})

# Argument naming the target path of a workspace-scoped tool.
PATH_ARG = "path"


@dataclass
class ApprovalVerdict:
    """Whether a tool call needs consent, and why."""

    required: bool
    reason: str = ""


def path_escapes_workspace(raw_path: str, workspace: str) -> bool:
    """True when a path resolves outside the workspace root."""
    if not os.path.isabs(raw_path):
        raw_path = os.path.join(workspace, raw_path)
    resolved = os.path.realpath(raw_path)
    root = os.path.realpath(workspace)
    try:
        return os.path.commonpath([resolved, root]) != root
    except ValueError:
        # Paths on different drives have no common path.
        return True


class ToolApprovalPolicy:
    """Classifies tool risk and tracks what the user allowed for this session."""

    def __init__(self, workspace: str, mode: ApprovalMode = DEFAULT_APPROVAL_MODE) -> None:
        self._workspace = workspace
        self._mode: ApprovalMode = mode
        self._session_allowlist: set[str] = set()

    @property
    def mode(self) -> ApprovalMode:
        return self._mode

    def set_mode(self, mode: str) -> ApprovalMode:
        """Set the approval mode, rejecting unknown values."""
        if mode not in VALID_APPROVAL_MODES:
            raise ValueError(f"Invalid approval mode: {mode!r}")
        self._mode = cast("ApprovalMode", mode)
        return self._mode

    def allow_for_session(self, tool_name: str) -> None:
        """Stop asking about a tool until the session ends."""
        self._session_allowlist.add(tool_name)

    def reset_session_allowlist(self) -> None:
        self._session_allowlist.clear()

    def get_session_allowlist(self) -> list[str]:
        return sorted(self._session_allowlist)

    def evaluate(self, tool_name: str, args: Any) -> ApprovalVerdict:
        """Decide whether this call needs user consent."""
        if self._mode == "auto":
            return ApprovalVerdict(required=False)
        if tool_name in self._session_allowlist:
            return ApprovalVerdict(required=False)
        if tool_name in READ_ONLY_TOOLS:
            return ApprovalVerdict(required=False)
        if tool_name in SHELL_TOOLS:
            return ApprovalVerdict(required=True, reason="Shell commands can run anything")

        if tool_name in WORKSPACE_SCOPED_TOOLS:
            path = args.get(PATH_ARG) if isinstance(args, dict) else None
            if isinstance(path, str) and path and not path_escapes_workspace(path, self._workspace):
                return ApprovalVerdict(required=False)
            return ApprovalVerdict(
                required=True,
                reason=f"{tool_name} writes outside the workspace ({path if isinstance(path, str) else 'no path'})",
            )

        # Unknown tools (extensions, custom tools) are gated rather than trusted.
        return ApprovalVerdict(required=True, reason=f"{tool_name} is not a recognized safe tool")

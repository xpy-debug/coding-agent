"""Bash tool: execute shell commands with streaming output and truncation."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from coding.agent.types import AgentTool, AgentToolResult, AgentToolUpdateCallback, ToolErrorDetail
from coding.ai.types import TextContent
from coding.core.truncate import TruncationResult, truncate_tail

BASH_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "The bash command to execute."},
        "timeout": {"type": "integer", "description": "Optional timeout in seconds."},
    },
    "required": ["command"],
}


@dataclass
class BashToolDetails:
    exit_code: int = 0
    truncation: TruncationResult | None = None
    full_output_path: str | None = None
    error: ToolErrorDetail | None = None


async def execute_bash(
    tool_call_id: str,
    params: dict[str, Any],
    cancel_event: asyncio.Event | None = None,
    on_update: AgentToolUpdateCallback | None = None,
    *,
    cwd: str = ".",
    timeout: float | None = None,
) -> AgentToolResult:
    """Execute a bash command and return its output."""
    command = params["command"]
    # Model-supplied timeout is clamped by the configured framework timeout
    model_timeout = params.get("timeout")
    if model_timeout is not None:
        timeout = min(float(model_timeout), timeout) if timeout is not None else float(model_timeout)

    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
        env={**os.environ, "TERM": "dumb"},
    )

    output_lines: list[str] = []
    full_output = []

    async def read_output() -> None:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace")
            output_lines.append(decoded)
            full_output.append(decoded)

            if on_update and len(output_lines) % 50 == 0:
                on_update(
                    AgentToolResult(
                        content=[TextContent(text="".join(output_lines[-50:]))],
                        details=BashToolDetails(),
                    )
                )

    timed_out = False
    try:
        if timeout:
            await asyncio.wait_for(read_output(), timeout=timeout)
        else:
            await read_output()

        await process.wait()
    except TimeoutError:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()
    except Exception:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        raise

    raw_output = "".join(output_lines)
    exit_code = process.returncode or 0

    # Truncate output
    truncation = truncate_tail(raw_output)
    details = BashToolDetails(exit_code=exit_code)

    if truncation.truncated:
        details.truncation = truncation
        # Write full output to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="coding-bash-") as f:
            f.write(raw_output)
            details.full_output_path = f.name

    if timed_out:
        details.error = ToolErrorDetail(
            type="timeout",
            tool="bash",
            message=f"Command timed out after {timeout}s",
            stdout=truncation.content,
            timed_out=True,
            timeout_seconds=timeout,
            output_truncated=truncation.truncated,
            full_output_path=details.full_output_path,
            hint="Shorten the command, pass a larger timeout, or split it into smaller steps.",
        )
        return AgentToolResult(content=[], details=details)

    result_text = truncation.content
    if exit_code != 0:
        result_text += f"\n[Exit code: {exit_code}]"

    return AgentToolResult(
        content=[TextContent(text=result_text)],
        details=details,
    )


def create_bash_tool(cwd: str, timeout: float | None = None) -> AgentTool:
    """Create a bash execution tool.

    `timeout` is the framework-configured upper bound in seconds; a model-supplied
    `timeout` argument is clamped to it. Bash manages its own subprocess timeout
    (including process kill), so AgentTool.timeout is left unset for the loop.
    """

    async def execute(
        tool_call_id: str,
        params: dict[str, Any],
        cancel_event: asyncio.Event | None = None,
        on_update: AgentToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        return await execute_bash(tool_call_id, params, cancel_event, on_update, cwd=cwd, timeout=timeout)

    return AgentTool(
        name="bash",
        description="Execute a bash command. Use for running scripts, installing packages, git operations, and other shell tasks.",
        parameters=BASH_SCHEMA,
        label="Bash",
        execute=execute,
    )

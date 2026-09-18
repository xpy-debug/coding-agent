"""Tests for the tool approval policy."""

from __future__ import annotations

import pytest

from coding.core.approval import (
    DEFAULT_APPROVAL_MODE,
    ToolApprovalPolicy,
    path_escapes_workspace,
)


def test_default_mode_is_auto():
    assert DEFAULT_APPROVAL_MODE == "auto"


def test_auto_mode_never_requires_approval(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "auto")

    assert policy.evaluate("bash", {"command": "rm -rf /"}).required is False
    assert policy.evaluate("write", {"path": "../escape.txt"}).required is False


@pytest.mark.parametrize("tool", ["read", "ls", "find", "grep"])
def test_read_only_tools_never_ask(tmp_path, tool):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    assert policy.evaluate(tool, {"path": "anything"}).required is False


def test_shell_commands_always_ask(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    verdict = policy.evaluate("bash", {"command": "echo hi"})

    assert verdict.required is True
    assert verdict.reason


def test_write_inside_workspace_is_allowed(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    assert policy.evaluate("write", {"path": "src/app.py"}).required is False
    assert policy.evaluate("edit", {"path": str(tmp_path / "deep" / "file.py")}).required is False


def test_write_outside_workspace_asks(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    verdict = policy.evaluate("write", {"path": "../escape.txt"})

    assert verdict.required is True
    assert "outside the workspace" in verdict.reason


def test_absolute_path_outside_workspace_asks(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    verdict = policy.evaluate("edit", {"path": str(tmp_path.parent / "elsewhere.txt")})

    assert verdict.required is True
    assert "outside the workspace" in verdict.reason


def test_symlink_escaping_workspace_asks(tmp_path):
    outside = tmp_path.parent / "outside_target.txt"
    outside.write_text("secret")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")

    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    assert policy.evaluate("edit", {"path": "link.txt"}).required is True


def test_write_without_a_usable_path_asks(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    assert policy.evaluate("write", {}).required is True
    assert policy.evaluate("write", {"path": ""}).required is True
    assert policy.evaluate("write", None).required is True


def test_unknown_tool_asks(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")

    verdict = policy.evaluate("some_extension_tool", {})

    assert verdict.required is True
    assert verdict.reason


def test_session_allowlist_suppresses_asking(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path), "ask")
    assert policy.evaluate("bash", {}).required is True

    policy.allow_for_session("bash")

    assert policy.evaluate("bash", {}).required is False
    assert policy.get_session_allowlist() == ["bash"]

    policy.reset_session_allowlist()

    assert policy.evaluate("bash", {}).required is True
    assert policy.get_session_allowlist() == []


def test_set_mode_rejects_unknown_values(tmp_path):
    policy = ToolApprovalPolicy(str(tmp_path))

    with pytest.raises(ValueError):
        policy.set_mode("yolo")

    assert policy.mode == "auto"
    assert policy.set_mode("ask") == "ask"
    assert policy.mode == "ask"


def test_path_escapes_workspace(tmp_path):
    assert path_escapes_workspace("inside.txt", str(tmp_path)) is False
    assert path_escapes_workspace(str(tmp_path / "deep" / "file.txt"), str(tmp_path)) is False
    assert path_escapes_workspace("../outside.txt", str(tmp_path)) is True
    assert path_escapes_workspace(str(tmp_path.parent), str(tmp_path)) is True

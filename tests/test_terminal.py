from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from actions import terminal
from actions.terminal import (
    MAX_OUTPUT_LENGTH,
    TRUNCATION_MARKER,
    terminal_run,
)


def test_terminal_run_is_discovered_as_a_write_action():
    from core.action_loader import discover_actions

    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=lambda _message: None,
    )

    assert "terminal_run" in registry.names()
    assert registry.risk_class("terminal_run") == "write"
    declaration = next(
        item
        for item in registry.get_tool_declarations()
        if item["name"] == "terminal_run"
    )
    assert declaration["parameters"]["required"] == ["command"]


@pytest.mark.parametrize(
    "command",
    ["echo hello", r"del /f /s C:\temp"],
)
def test_terminal_run_requires_confirmation_then_executes_command(
    command, monkeypatch
):
    run = Mock(return_value=SimpleNamespace(
        stdout="hello\n",
        stderr="",
        returncode=0,
    ))
    monkeypatch.setattr(terminal.subprocess, "run", run)

    pending = terminal_run({"command": command})

    assert pending == {
        "result": "Ask the user for explicit confirmation",
        "command": command,
    }
    run.assert_not_called()

    result = terminal_run({"command": command, "confirmed": True})

    assert result == {"stdout": "hello\n", "stderr": "", "returncode": 0}
    run.assert_called_once_with(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=None,
        encoding="utf-8",
        errors="replace",
    )


def test_terminal_run_returns_timeout_after_confirmation(monkeypatch):
    run = Mock(side_effect=terminal.subprocess.TimeoutExpired("sleep 5", 1))
    monkeypatch.setattr(terminal.subprocess, "run", run)

    result = terminal_run({
        "command": "sleep 5",
        "timeout": 1,
        "confirmed": True,
    })

    assert result == {"stdout": "", "stderr": "timeout", "returncode": -1}
    run.assert_called_once()


def test_terminal_run_truncates_long_stdout_and_stderr(monkeypatch):
    run = Mock(return_value=SimpleNamespace(
        stdout="x" * (MAX_OUTPUT_LENGTH + 1),
        stderr="y" * (MAX_OUTPUT_LENGTH + 1),
        returncode=0,
    ))
    monkeypatch.setattr(terminal.subprocess, "run", run)

    result = terminal_run({"command": "echo hello", "confirmed": True})

    assert result["stdout"] == "x" * MAX_OUTPUT_LENGTH + TRUNCATION_MARKER
    assert result["stderr"] == "y" * MAX_OUTPUT_LENGTH + TRUNCATION_MARKER
    assert result["returncode"] == 0

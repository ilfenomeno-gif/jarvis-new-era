from pathlib import Path
from types import SimpleNamespace

import pytest

from actions.terminal import (
    MAX_OUTPUT_LENGTH,
    TRUNCATION_MARKER,
    terminal_run,
)
from core.terminal_agent import TerminalAgent


class FakeTerminalAgent:
    def __init__(self, stdout="hello\n", stderr="", return_code=0, pid=42):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.pid = pid
        self.commands = []
        self.visible_commands = []

    def execute(self, command):
        self.commands.append(command)
        return SimpleNamespace(
            stdout=self.stdout,
            stderr=self.stderr,
            return_code=self.return_code,
        )

    def execute_visible(self, command):
        self.visible_commands.append(command)
        return self.pid


def test_terminal_run_is_discovered_as_a_guarded_write_action():
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
    assert "guarded Terminal Agent" in declaration["description"]


def test_terminal_run_requires_confirmation_then_returns_output_for_chat():
    agent = FakeTerminalAgent()

    pending = terminal_run({"command": "echo hello"}, terminal_agent=agent)

    assert pending == {
        "result": "Ask the user for explicit confirmation",
        "command": "echo hello",
    }
    assert agent.commands == []

    result = terminal_run(
        {"command": "echo hello", "confirmed": True},
        terminal_agent=agent,
    )

    assert result == {
        "stdout": "hello\n",
        "stderr": "",
        "returncode": 0,
    }
    assert agent.commands == ["echo hello"]


def test_terminal_run_visible_mode_uses_terminal_agent():
    agent = FakeTerminalAgent(pid=2345)

    result = terminal_run(
        {"command": "echo hello", "confirmed": True, "mode": "visible"},
        terminal_agent=agent,
    )

    assert result == {
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "pid": 2345,
        "mode": "visible",
    }
    assert agent.visible_commands == ["echo hello"]
    assert agent.commands == []


def test_terminal_policy_blocks_non_allowlisted_commands(tmp_path):
    calls = []
    agent = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    result = terminal_run(
        {"command": "python -c print(1)", "confirmed": True},
        terminal_agent=agent,
    )

    assert result["returncode"] == 126
    assert "override required" in result["stderr"]
    assert calls == []


def test_terminal_output_is_truncated_before_it_reaches_chat():
    agent = FakeTerminalAgent(
        stdout="x" * (MAX_OUTPUT_LENGTH + 1),
        stderr="y" * (MAX_OUTPUT_LENGTH + 1),
    )

    result = terminal_run(
        {"command": "echo hello", "confirmed": True},
        terminal_agent=agent,
    )

    assert result["stdout"] == "x" * MAX_OUTPUT_LENGTH + TRUNCATION_MARKER
    assert result["stderr"] == "y" * MAX_OUTPUT_LENGTH + TRUNCATION_MARKER


def test_terminal_output_sink_receives_untruncated_output():
    stdout = "x" * (MAX_OUTPUT_LENGTH + 100)
    received = []
    result = terminal_run(
        {"command": "echo hello", "confirmed": True},
        terminal_agent=FakeTerminalAgent(stdout=stdout),
        terminal_output_sink=lambda out, err: received.append((out, err)),
    )
    assert received == [(stdout, "")]
    assert result["stdout"].endswith(TRUNCATION_MARKER)

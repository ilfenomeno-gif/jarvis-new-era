from __future__ import annotations

import asyncio
import subprocess

import pytest

from adapters.terminal import GuardedTerminalAdapter
from agents.contracts import ActionContext
from agents.terminal_plugin import TerminalRunPlugin
from capabilities.contracts import ToolCall
from capabilities.terminal import (
    TerminalAuthorizationRequired,
    TerminalCommandRejected,
    TerminalCommandResult,
)
from core.terminal_agent import TerminalAgent
from orchestrator.plugins import AgentRegistry


class _Authorizer:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[ToolCall, ActionContext]] = []

    async def authorize(self, call: ToolCall, context: ActionContext) -> bool:
        self.calls.append((call, context))
        return self.allowed


class _TerminalExecutor:
    def __init__(self, result: TerminalCommandResult | Exception) -> None:
        self.result = result
        self.commands: list[str] = []

    def execute(self, command: str) -> TerminalCommandResult:
        self.commands.append(command)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _call(command: str = "echo approved") -> ToolCall:
    return ToolCall("terminal-call-1", "terminal_run", {"command": command})


def test_terminal_plugin_requires_confirmation_before_execution():
    executor = _TerminalExecutor(TerminalCommandResult(0, "ok", ""))
    authorizer = _Authorizer(allowed=False)
    context = ActionContext("terminal-session", user_id="test-user")
    plugin = TerminalRunPlugin(executor, authorizer)

    reply = asyncio.run(plugin.execute(_call(), context))

    assert reply.status == "ask"
    assert authorizer.calls == [(_call(), context)]
    assert executor.commands == []


def test_terminal_plugin_returns_guarded_command_result():
    executor = _TerminalExecutor(TerminalCommandResult(0, "approved\n", ""))
    authorizer = _Authorizer(allowed=True)
    plugin = TerminalRunPlugin(executor, authorizer)
    context = ActionContext("terminal-session", user_id="test-user")
    registry = AgentRegistry((plugin,))

    reply = asyncio.run(registry.dispatch(_call(), context))

    assert reply.status == "done"
    assert reply.content == "approved\n"
    assert reply.facts == {"return_code": 0, "stderr": ""}
    assert executor.commands == ["echo approved"]
    assert authorizer.calls == [(_call(), context)]


def test_terminal_plugin_preserves_exit_failure_and_bounds_output():
    long_output = "x" * 4100
    plugin = TerminalRunPlugin(
        _TerminalExecutor(TerminalCommandResult(7, long_output, "failed")),
        _Authorizer(allowed=True),
    )

    reply = asyncio.run(plugin.execute(_call(), ActionContext("terminal-session")))

    assert reply.status == "failed"
    assert reply.content.startswith("x" * 4000)
    assert reply.content.endswith("[...output truncated]")
    assert reply.facts["return_code"] == 7


@pytest.mark.parametrize(
    ("exception", "status"),
    [
        (TerminalAuthorizationRequired("override required"), "ask"),
        (TerminalCommandRejected("command blocked"), "failed"),
    ],
)
def test_terminal_plugin_maps_policy_and_execution_errors(exception, status):
    plugin = TerminalRunPlugin(_TerminalExecutor(exception), _Authorizer(allowed=True))

    reply = asyncio.run(plugin.execute(_call(), ActionContext("terminal-session")))

    assert reply.status == status
    assert reply.content in {"override required", "command blocked"}


def test_terminal_plugin_rejects_empty_command_before_authorization():
    authorizer = _Authorizer(allowed=True)
    plugin = TerminalRunPlugin(
        _TerminalExecutor(TerminalCommandResult(0, "", "")),
        authorizer,
    )

    with pytest.raises(ValueError, match="non-empty command"):
        asyncio.run(
            plugin.execute(_call(" "), ActionContext("terminal-session"))
        )

    assert authorizer.calls == []


def test_guarded_terminal_adapter_preserves_terminal_policy_and_result(tmp_path):
    runner_calls = []

    def runner(args, **kwargs):
        runner_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "approved\n", "")

    legacy_terminal = TerminalAgent(
        database_path=tmp_path / "terminal.sqlite3",
        runner=runner,
    )
    adapter = GuardedTerminalAdapter(legacy_terminal)

    result = adapter.execute("echo approved")

    assert result == TerminalCommandResult(0, "approved\n", "")
    assert runner_calls[0][1]["shell"] is False

from __future__ import annotations

import asyncio

import pytest

from agents.computer_agent import ComputerTaskResult
from agents.computer_plugin import ComputerTaskPlugin
from agents.contracts import ActionContext
from capabilities.contracts import ToolCall


class _Authorizer:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[ToolCall, ActionContext]] = []

    async def authorize(self, call: ToolCall, context: ActionContext) -> bool:
        self.calls.append((call, context))
        return self.allowed


class _ComputerAgent:
    def __init__(self, result: ComputerTaskResult) -> None:
        self.result = result
        self.tasks: list[str] = []

    def execute_task(self, task: str) -> ComputerTaskResult:
        self.tasks.append(task)
        return self.result


def test_computer_plugin_requires_authorization_before_executing():
    call = ToolCall("call-1", "computer_task", {"task": "local: click Save"})
    agent = _ComputerAgent(ComputerTaskResult("local", True, "Clicked Save.", "Save"))
    authorizer = _Authorizer(allowed=False)
    plugin = ComputerTaskPlugin(agent, authorizer)
    context = ActionContext("session-1", user_id="user-1")

    reply = asyncio.run(plugin.execute(call, context))

    assert reply.status == "ask"
    assert reply.call_id == call.call_id
    assert reply.name == call.name
    assert authorizer.calls == [(call, context)]
    assert agent.tasks == []


def test_computer_plugin_maps_authorized_success_to_done():
    call = ToolCall("call-2", "computer_task", {"task": "Cerca Jarvis su Google"})
    agent = _ComputerAgent(
        ComputerTaskResult("web", True, "Search completed.", target=None)
    )
    plugin = ComputerTaskPlugin(agent, _Authorizer(allowed=True))

    reply = asyncio.run(plugin.execute(call, ActionContext("session-2")))

    assert reply.status == "done"
    assert reply.content == "Search completed."
    assert reply.facts == {"mode": "web", "target": None}
    assert agent.tasks == ["Cerca Jarvis su Google"]


def test_computer_plugin_maps_agent_failure_to_failed():
    agent = _ComputerAgent(ComputerTaskResult("local", False, "Target missing.", "Save"))
    plugin = ComputerTaskPlugin(agent, _Authorizer(allowed=True))

    reply = asyncio.run(
        plugin.execute(
            ToolCall("call-3", "computer_task", {"task": "local: click Save"}),
            ActionContext("session-3"),
        )
    )

    assert reply.status == "failed"
    assert reply.content == "Target missing."


def test_computer_plugin_maps_missing_visible_target_to_failed():
    class MissingTargetAgent:
        def execute_task(self, _task: str) -> ComputerTaskResult:
            raise LookupError("Could not find 'Save'; no input was sent.")

    plugin = ComputerTaskPlugin(MissingTargetAgent(), _Authorizer(allowed=True))

    reply = asyncio.run(
        plugin.execute(
            ToolCall("call-missing", "computer_task", {"task": "local: click Save"}),
            ActionContext("session-missing"),
        )
    )

    assert reply.status == "failed"
    assert reply.content == "Could not find 'Save'; no input was sent."


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("other_tool", {"task": "x"}, ValueError),
        ("computer_task", {}, ValueError),
        ("computer_task", {"task": " "}, ValueError),
    ],
)
def test_computer_plugin_rejects_invalid_calls(name, arguments, error):
    plugin = ComputerTaskPlugin(
        _ComputerAgent(ComputerTaskResult("local", True, "ok")),
        _Authorizer(allowed=True),
    )

    with pytest.raises(error):
        asyncio.run(
            plugin.execute(ToolCall("invalid", name, arguments), ActionContext("test"))
        )


def test_computer_agent_module_does_not_import_core_or_ui():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import agents.computer_agent; "
                "assert not any(name == 'core' or name.startswith('core.') "
                "for name in sys.modules); "
                "assert 'PyQt6' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

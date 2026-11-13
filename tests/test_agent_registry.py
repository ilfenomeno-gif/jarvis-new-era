from __future__ import annotations

import asyncio

import pytest

from agents.computer_agent import ComputerTaskResult
from agents.computer_plugin import ComputerTaskPlugin
from agents.contracts import ActionContext
from capabilities.contracts import ToolCall, ToolReply
from orchestrator.plugins import AgentRegistry


class _Authorizer:
    async def authorize(
        self,
        _call: ToolCall,
        _context: ActionContext,
    ) -> bool:
        return True


class _ComputerAgent:
    def execute_task(self, task: str) -> ComputerTaskResult:
        return ComputerTaskResult("web", True, f"Completed: {task}")


def test_registry_dispatches_to_the_registered_computer_plugin():
    plugin = ComputerTaskPlugin(_ComputerAgent(), _Authorizer())
    registry = AgentRegistry((plugin,))

    reply = asyncio.run(
        registry.dispatch(
            ToolCall("computer-1", "computer_task", {"task": "Cerca Jarvis su Google"}),
            ActionContext("session-1"),
        )
    )

    assert reply == ToolReply(
        call_id="computer-1",
        name="computer_task",
        status="done",
        content="Completed: Cerca Jarvis su Google",
        facts={"mode": "web", "target": None},
    )


def test_registry_rejects_duplicate_plugin_names():
    plugin = ComputerTaskPlugin(_ComputerAgent(), _Authorizer())

    with pytest.raises(ValueError, match="is registered"):
        AgentRegistry((plugin, plugin))


def test_registry_rejects_unregistered_tools():
    registry = AgentRegistry()

    with pytest.raises(LookupError, match="No agent plugin"):
        asyncio.run(
            registry.dispatch(
                ToolCall("missing-1", "unknown", {}), ActionContext("session-1")
            )
        )


def test_registry_rejects_plugin_reply_for_a_different_call():
    class WrongReplyPlugin:
        name = "wrong_reply"

        async def execute(
            self,
            _call: ToolCall,
            _context: ActionContext,
        ) -> ToolReply:
            return ToolReply("other-call", "wrong_reply", "done", "stale")

    registry = AgentRegistry((WrongReplyPlugin(),))

    with pytest.raises(ValueError, match="does not match"):
        asyncio.run(
            registry.dispatch(
                ToolCall("requested-call", "wrong_reply", {}),
                ActionContext("session-1"),
            )
        )

"""Orchestrator-facing adapter for the injected computer-use agent."""

from __future__ import annotations

from agents.computer_agent import ComputerAgent
from agents.contracts import ActionAuthorizer, ActionContext
from capabilities.contracts import ToolCall, ToolReply


class ComputerTaskPlugin:
    """Run computer tasks only after the injected authorizer permits them."""

    name = "computer_task"

    def __init__(self, agent: ComputerAgent, authorizer: ActionAuthorizer) -> None:
        if not callable(getattr(agent, "execute_task", None)):
            raise TypeError("agent must provide execute_task().")
        if not callable(getattr(authorizer, "authorize", None)):
            raise TypeError("authorizer must provide authorize().")
        self._agent = agent
        self._authorizer = authorizer

    async def execute(self, call: ToolCall, context: ActionContext) -> ToolReply:
        if not isinstance(call, ToolCall):
            raise TypeError("call must be a ToolCall.")
        if not isinstance(context, ActionContext):
            raise TypeError("context must be an ActionContext.")
        if call.name != self.name:
            raise ValueError(f"Unsupported tool for {self.name!r}: {call.name!r}.")
        task = call.arguments.get("task")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("computer_task requires a non-empty task.")

        authorized = await self._authorizer.authorize(call, context)
        if not isinstance(authorized, bool):
            raise TypeError("ActionAuthorizer.authorize() must return a boolean.")
        if not authorized:
            return ToolReply(
                call_id=call.call_id,
                name=call.name,
                status="ask",
                content="The computer task requires explicit authorization.",
            )

        try:
            result = self._agent.execute_task(task)
        except (LookupError, ValueError) as exc:
            return ToolReply(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                content=str(exc),
                facts={"task": task},
            )
        return ToolReply(
            call_id=call.call_id,
            name=call.name,
            status="done" if result.success else "failed",
            content=result.summary,
            facts={"mode": result.mode, "target": result.target},
        )

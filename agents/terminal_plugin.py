"""Orchestrator plugin for the existing guarded terminal capability."""

from __future__ import annotations

from agents.contracts import ActionAuthorizer, ActionContext
from capabilities.contracts import ToolCall, ToolReply
from capabilities.terminal import (
    TerminalAuthorizationRequired,
    TerminalCommandRejected,
    TerminalExecutor,
)

MAX_TERMINAL_OUTPUT_LENGTH = 4000


def _bounded_output(text: str) -> str:
    if len(text) <= MAX_TERMINAL_OUTPUT_LENGTH:
        return text
    return text[:MAX_TERMINAL_OUTPUT_LENGTH] + "\n[...output truncated]"


class TerminalRunPlugin:
    name = "terminal_run"

    def __init__(
        self,
        terminal: TerminalExecutor,
        authorizer: ActionAuthorizer,
    ) -> None:
        if not callable(getattr(terminal, "execute", None)):
            raise TypeError("terminal must provide execute().")
        if not callable(getattr(authorizer, "authorize", None)):
            raise TypeError("authorizer must provide authorize().")
        self._terminal = terminal
        self._authorizer = authorizer

    async def execute(self, call: ToolCall, context: ActionContext) -> ToolReply:
        if not isinstance(call, ToolCall):
            raise TypeError("call must be a ToolCall.")
        if not isinstance(context, ActionContext):
            raise TypeError("context must be an ActionContext.")
        if call.name != self.name:
            raise ValueError(f"Unsupported tool for {self.name!r}: {call.name!r}.")
        command = call.arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("terminal_run requires a non-empty command.")

        authorized = await self._authorizer.authorize(call, context)
        if not isinstance(authorized, bool):
            raise TypeError("ActionAuthorizer.authorize() must return a boolean.")
        if not authorized:
            return ToolReply(
                call_id=call.call_id,
                name=call.name,
                status="ask",
                content="The terminal command requires explicit user confirmation.",
            )

        try:
            result = self._terminal.execute(command)
        except TerminalAuthorizationRequired as exc:
            return ToolReply(
                call_id=call.call_id,
                name=call.name,
                status="ask",
                content=str(exc),
            )
        except TerminalCommandRejected as exc:
            return ToolReply(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                content=str(exc),
            )

        return_code = result.return_code
        output = _bounded_output(result.stdout)
        error = _bounded_output(result.stderr)
        return ToolReply(
            call_id=call.call_id,
            name=call.name,
            status="done" if return_code == 0 else "failed",
            content=output or error or f"Command exited with code {return_code}.",
            facts={"return_code": return_code, "stderr": error},
        )

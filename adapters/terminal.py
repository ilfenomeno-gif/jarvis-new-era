"""Adapter from the guarded legacy terminal agent to the terminal capability."""

from __future__ import annotations

from capabilities.terminal import (
    TerminalAuthorizationRequired,
    TerminalCommandRejected,
    TerminalCommandResult,
)
from core.terminal_agent import (
    CommandBlocked,
    OverrideRequired,
    TerminalAgent,
    TerminalExecutionError,
)


class GuardedTerminalAdapter:
    def __init__(self, terminal: TerminalAgent) -> None:
        self._terminal = terminal

    def execute(self, command: str) -> TerminalCommandResult:
        try:
            result = self._terminal.execute(command)
        except OverrideRequired as exc:
            raise TerminalAuthorizationRequired(str(exc)) from exc
        except (CommandBlocked, TerminalExecutionError) as exc:
            raise TerminalCommandRejected(str(exc)) from exc
        return TerminalCommandResult(
            return_code=result.return_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )

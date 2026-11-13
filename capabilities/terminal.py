"""Provider-neutral contract for guarded command execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TerminalCommandResult:
    return_code: int
    stdout: str
    stderr: str


class TerminalAuthorizationRequired(PermissionError):
    """The existing command policy requires a separate explicit override."""


class TerminalCommandRejected(RuntimeError):
    """The command was blocked or failed before producing an execution result."""


class TerminalExecutor(Protocol):
    def execute(self, command: str) -> TerminalCommandResult: ...

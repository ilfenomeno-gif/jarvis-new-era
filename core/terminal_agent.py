"""Guarded, non-shell terminal execution and one-command user overrides."""

from __future__ import annotations

import os
import re
import shlex
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from core.internal_workflow import default_database_path
from core.phone_channel import PhoneMessage
from core.terminal_guard import PolicyResult, TerminalGuard

OVERRIDE_TOKEN = "AUTORIZZO OVERRIDE"


class OverrideRequired(PermissionError):
    def __init__(self, result: PolicyResult) -> None:
        self.result = result
        super().__init__(f"Command blocked by policy: {result.reason}")


class CommandBlocked(PermissionError):
    pass


class TerminalExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: str
    return_code: int
    stdout: str
    stderr: str


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class TerminalAgent:
    def __init__(
        self,
        guard: TerminalGuard | None = None,
        *,
        database_path: str | Path | None = None,
        runner: Runner = subprocess.run,
        timeout_seconds: float = 10,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
        ):
            raise ValueError("timeout_seconds must be greater than 0 and at most 120.")
        self.guard = guard or TerminalGuard()
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.runner = runner
        self.timeout_seconds = float(timeout_seconds)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS terminal_policies (
                    policy_hash TEXT PRIMARY KEY,
                    policy_path TEXT NOT NULL,
                    policy_yaml TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS terminal_overrides (
                    override_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    command TEXT NOT NULL,
                    block_reason TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    return_code INTEGER,
                    duration_seconds REAL NOT NULL DEFAULT 0
                );
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO terminal_policies (
                    policy_hash, policy_path, policy_yaml, recorded_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self.guard.policy.sha256,
                    str(self.guard.policy.source),
                    self.guard.policy.content,
                    _now(),
                ),
            )

    @staticmethod
    def _argv_for_execution(argv: tuple[str, ...]) -> tuple[str, ...]:
        # Windows has no standalone echo executable. Use Python to print the same
        # already-tokenized arguments rather than invoking cmd.exe or a shell.
        if os.name == "nt" and Path(argv[0]).name.casefold() == "echo":
            script = "import sys; print(' '.join(sys.argv[1:]))"
            return (sys.executable, "-c", script, *argv[1:])
        return argv

    def _run(self, result: PolicyResult) -> CommandResult:
        try:
            completed = self.runner(
                self._argv_for_execution(result.argv),
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise TerminalExecutionError(
                f"Command exceeded the {self.timeout_seconds:g}-second execution limit."
            ) from None
        except OSError as exc:
            raise TerminalExecutionError(
                f"Command could not be started ({type(exc).__name__})."
            ) from None
        except Exception as exc:
            raise TerminalExecutionError(
                f"Command execution failed ({type(exc).__name__})."
            ) from None
        return CommandResult(
            command=result.command,
            return_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def execute(self, command: str) -> CommandResult:
        result = self.guard.inspect(command)
        if result.requires_override:
            raise OverrideRequired(result)
        if result.blocked or not result.allowed:
            raise CommandBlocked(result.reason)
        return self._run(result)

    def execute_visible(self, command: str) -> int:
        """Launch one allowlisted command in a new visible Windows console."""
        if os.name != "nt":
            raise TerminalExecutionError(
                "Visible terminal sessions are supported on Windows only."
            )
        result = self.guard.inspect(command)
        if result.requires_override:
            raise OverrideRequired(result)
        if result.blocked or not result.allowed:
            raise CommandBlocked(result.reason)
        creation_flag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
        if creation_flag is None:
            raise TerminalExecutionError("Windows console creation is unavailable.")
        try:
            process = subprocess.Popen(
                self._argv_for_execution(result.argv),
                shell=False,
                creationflags=creation_flag,
                close_fds=True,
            )
        except OSError as exc:
            raise TerminalExecutionError(
                f"Command could not be started ({type(exc).__name__})."
            ) from None
        return int(process.pid)

    def execute_with_override(
        self,
        command: str,
        token: str,
        *,
        user_id: str | None = None,
    ) -> CommandResult:
        if not isinstance(token, str) or token.strip() != OVERRIDE_TOKEN:
            raise PermissionError("A valid explicit override token is required.")
        result = self.guard.inspect(command)
        if result.blocked and not result.requires_override:
            raise CommandBlocked(result.reason)
        if not result.requires_override:
            raise ValueError("Override is only valid for a command blocked by policy.")
        if not result.argv:
            raise CommandBlocked("Malformed commands cannot be overridden.")
        safe_user_id = str(user_id or "")[:200]
        override_id = uuid.uuid4().hex
        started = datetime.now(UTC)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO terminal_overrides (
                    override_id, occurred_at, command, block_reason,
                    user_id, status
                ) VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (
                    override_id,
                    started.isoformat(timespec="milliseconds"),
                    command,
                    result.reason,
                    safe_user_id,
                ),
            )
        try:
            command_result = self._run(result)
        except TerminalExecutionError as exc:
            self._finish_override(
                override_id,
                "failed",
                None,
                (datetime.now(UTC) - started).total_seconds(),
            )
            raise exc
        self._finish_override(
            override_id,
            "completed" if command_result.return_code == 0 else "failed",
            command_result.return_code,
            (datetime.now(UTC) - started).total_seconds(),
        )
        return command_result

    def _finish_override(
        self,
        override_id: str,
        status: str,
        return_code: int | None,
        duration: float,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE terminal_overrides SET status = ?, return_code = ?,
                    duration_seconds = ? WHERE override_id = ?
                """,
                (status, return_code, max(0.0, duration), override_id),
            )

    def handle_phone_override(self, message: PhoneMessage) -> str:
        match = re.match(
            rf"^\s*{re.escape(OVERRIDE_TOKEN)}\s*:\s*(.+?)\s*$",
            message.text,
            re.IGNORECASE | re.DOTALL,
        )
        if match is None:
            return (
                "Formato richiesto: AUTORIZZO OVERRIDE: <comando bloccato>. "
                "L'autorizzazione vale per un solo comando."
            )
        command = match.group(1).strip()
        try:
            result = self.execute_with_override(
                command,
                OVERRIDE_TOKEN,
                user_id=message.sender_id,
            )
        except (CommandBlocked, OverrideRequired, PermissionError, ValueError) as exc:
            return f"Override non eseguito: {exc}"
        except TerminalExecutionError as exc:
            return f"Override fallito: {exc}"
        output = result.stdout.strip() or result.stderr.strip() or "(nessun output)"
        return (
            f"Comando autorizzato completato con codice {result.return_code}:\n"
            f"{output[:2000]}"
        )

"""Run one guarded, non-interactive terminal command and publish its result."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from core.audit_log import AuditLog
from core.guardrails import redact_sensitive, resolve_safe_path
from core.terminal_guard import TerminalGuard, load_policy

_active_lock = threading.Lock()
_active_processes: dict[str, subprocess.Popen] = {}
_BASE_DIR = Path(__file__).resolve().parents[1]


def _policy_options() -> tuple[dict, list[str], list[str]]:
    policy = load_policy()
    raw = yaml.safe_load(policy.content)
    if not isinstance(raw, dict):
        raise ValueError("Terminal policy must be a YAML object.")
    timeout = raw.get("timeout_seconds", 30)
    max_output = raw.get("max_output_bytes", 8000)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError("terminal timeout_seconds must be between 0 and 120.")
    if isinstance(max_output, bool) or not isinstance(max_output, int) or not 1 <= max_output <= 1_000_000:
        raise ValueError("terminal max_output_bytes must be between 1 and 1000000.")
    required = raw.get("require_override_commands", [])
    denied = raw.get("deny_commands", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise ValueError("require_override_commands must be a string list.")
    if not isinstance(denied, list) or any(not isinstance(item, str) for item in denied):
        raise ValueError("deny_commands must be a string list.")
    return (
        {"timeout_seconds": float(timeout), "max_output_bytes": max_output},
        required,
        denied,
    )


def _normalized_command(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().replace("\\", "/")).casefold()


def _matches_deny(command: str, deny_commands: list[str]) -> bool:
    normalized = _normalized_command(command)
    for denied in deny_commands:
        pattern = _normalized_command(denied)
        if not pattern:
            continue
        regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
        if re.fullmatch(regex, normalized) or re.match(rf"{regex}(?:\s|$)", normalized):
            return True
    return False


def _requires_confirmation(command: str, required_commands: list[str]) -> bool:
    normalized = _normalized_command(command)
    return any(
        normalized == prefix or normalized.startswith(prefix + " ")
        for item in required_commands
        if (prefix := _normalized_command(item))
    )


def _truncate_bytes(value: str, limit: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return value
    marker = b"\n[...output truncated]"
    if limit <= len(marker):
        return encoded[:limit].decode("utf-8", errors="ignore")
    available = max(0, limit - len(marker))
    return encoded[:available].decode("utf-8", errors="ignore") + marker.decode()


def _emit(event: str, **payload: Any) -> None:
    from core.actions_bridge import push_event

    push_event("terminal", {"event": event, **payload})


def _audit(command: str, outcome: str, detail: str = "") -> None:
    AuditLog(_BASE_DIR / "config" / "audit.jsonl").record(
        tool="terminal_exec",
        outcome=outcome,
        scope="terminal",
        arguments={"command": redact_sensitive(command)},
        detail=redact_sensitive(detail)[:2000],
    )


def kill_active() -> bool:
    with _active_lock:
        processes = list(_active_processes.values())
    for process in processes:
        if process.poll() is None:
            process.kill()
            return True
    return False


def _command_argv(argv: tuple[str, ...]) -> tuple[str, ...]:
    if os.name == "nt" and Path(argv[0]).name.casefold() == "echo":
        return (sys.executable, "-c", "import sys; print(' '.join(sys.argv[1:]))", *argv[1:])
    return argv


def _run_confirmed(
    command: str,
    cwd: str | None,
    guard: TerminalGuard,
    timeout: float,
    max_output_bytes: int,
) -> dict[str, Any]:
    result = guard.inspect(command)
    if result.blocked and not result.requires_override or not result.argv:
        message = result.reason or "Command is blocked by terminal policy."
        _emit("blocked", command=command, reason=message, cwd=cwd or os.getcwd())
        _audit(command, "blocked", message)
        return {"ok": False, "error": "blocked", "reason": message}
    try:
        working_directory = resolve_safe_path(cwd) if cwd else Path.cwd()
        if not working_directory.is_dir():
            raise NotADirectoryError("cwd must be an existing directory.")
    except (OSError, TypeError, ValueError, PermissionError) as exc:
        message = f"Invalid working directory: {exc}"
        _emit("error", command=command, reason=message, cwd=cwd or os.getcwd())
        _audit(command, "failed", message)
        return {"ok": False, "error": "invalid_cwd", "reason": message}

    execution_id = uuid.uuid4().hex
    safe_command = redact_sensitive(command)
    _emit("start", command=safe_command, cwd=str(working_directory), status="running")
    _audit(command, "started")
    try:
        process = subprocess.Popen(
            _command_argv(result.argv),
            cwd=working_directory,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with _active_lock:
            _active_processes[execution_id] = process
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            output = _truncate_bytes(stdout or "", max_output_bytes)
            error = _truncate_bytes(stderr or "", max_output_bytes)
            reason = f"Command exceeded the {timeout:g}-second timeout."
            _emit(
                "timeout",
                command=safe_command,
                cwd=str(working_directory),
                stdout=output,
                stderr=error,
                reason=reason,
                returncode=process.returncode,
            )
            _audit(command, "timeout", reason)
            return {"ok": False, "error": "timeout", "stdout": output, "stderr": error, "returncode": process.returncode}
        output = _truncate_bytes(stdout or "", max_output_bytes)
        error = _truncate_bytes(stderr or "", max_output_bytes)
        _emit(
            "output",
            command=safe_command,
            cwd=str(working_directory),
            stdout=output,
            stderr=error,
            returncode=process.returncode,
            status="ok" if process.returncode == 0 else "error",
        )
        _audit(command, "completed" if process.returncode == 0 else "failed", error)
        return {
            "ok": process.returncode == 0,
            "stdout": output,
            "stderr": error,
            "returncode": process.returncode,
            "cwd": str(working_directory),
        }
    except OSError as exc:
        reason = f"Command could not be started ({type(exc).__name__}): {exc}"
        _emit("error", command=safe_command, cwd=str(working_directory), reason=reason)
        _audit(command, "failed", reason)
        return {"ok": False, "error": "execution_error", "reason": reason}
    finally:
        with _active_lock:
            _active_processes.pop(execution_id, None)


def run(
    parameters: dict[str, Any] | str | None = None,
    *,
    terminal_agent=None,
    command: str | None = None,
    cwd: str | None = None,
    force: bool = False,
    **_context: Any,
) -> dict[str, Any]:
    if parameters is not None and not isinstance(parameters, (dict, str)):
        return {"ok": False, "error": "invalid_parameters"}
    if isinstance(parameters, str):
        command = parameters
        values: dict[str, Any] = {}
    else:
        values = parameters or {}
    command = command if command is not None else values.get("command")
    cwd = cwd if cwd is not None else values.get("cwd")
    force = force or values.get("force", False)
    if not isinstance(command, str) or not command.strip():
        return {"ok": False, "error": "invalid_command", "reason": "command must be non-empty text."}
    if force is True:
        _emit("blocked", command=command, reason="force cannot bypass user confirmation.")
        return {"ok": False, "error": "blocked", "reason": "force cannot bypass user confirmation."}
    if force is not False and force is not None:
        return {"ok": False, "error": "invalid_force", "reason": "force must be a boolean."}
    if cwd is not None and not isinstance(cwd, str):
        return {"ok": False, "error": "invalid_cwd", "reason": "cwd must be text or null."}

    options, required, denied = _policy_options()
    guard = terminal_agent.guard if terminal_agent is not None else TerminalGuard()
    decision = guard.inspect(command)
    if _matches_deny(command, denied):
        reason = "Command matches the terminal deny-list."
        _emit("blocked", command=command, reason=reason, cwd=cwd or os.getcwd())
        _audit(command, "blocked", reason)
        return {"ok": False, "error": "blocked", "reason": reason}
    if decision.blocked and not decision.requires_override:
        _emit("blocked", command=command, reason=decision.reason, cwd=cwd or os.getcwd())
        _audit(command, "blocked", decision.reason)
        return {"ok": False, "error": "blocked", "reason": decision.reason}

    if decision.requires_override or _requires_confirmation(command, required):
        from core import confirm

        active_confirmation = confirm.pending_title()
        if active_confirmation:
            reason = f"Another confirmation is already pending: {active_confirmation}"
            _emit("blocked", command=command, reason=reason, cwd=cwd or os.getcwd())
            _audit(command, "blocked", reason)
            return {"ok": False, "error": "confirmation_pending", "reason": reason}

        key = f"terminal-exec-{uuid.uuid4().hex}"
        message = confirm.request(
            key,
            "Comando terminale in attesa di conferma",
            command,
            lambda: _run_confirmed(
                command,
                cwd,
                guard,
                options["timeout_seconds"],
                options["max_output_bytes"],
            ).get("stdout", ""),
            on_cancel=lambda: _emit(
                "cancelled",
                command=redact_sensitive(command),
                cwd=cwd or os.getcwd(),
            ),
        )
        if "[CONFIRMATION_PENDING]" not in message:
            _emit("blocked", command=command, reason=message, cwd=cwd or os.getcwd())
            _audit(command, "blocked", message)
            return {"ok": False, "error": "confirmation_unavailable", "reason": message}
        return {"ok": False, "pending": True, "confirm_key": key}

    return _run_confirmed(
        command,
        cwd,
        guard,
        options["timeout_seconds"],
        options["max_output_bytes"],
    )


TOOL = {
    "name": "terminal_exec",
    "description": (
        "Execute one non-interactive command through the terminal policy. "
        "Allowlisted commands return captured output; policy overrides require "
        "the user's confirmation banner. The force parameter never bypasses confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {"type": "STRING"},
            "cwd": {"type": "STRING", "nullable": True},
            "force": {"type": "BOOLEAN", "default": False},
        },
        "required": ["command"],
    },
    "risk_class": "write",
    "handler": run,
}

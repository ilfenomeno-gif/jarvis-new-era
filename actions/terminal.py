"""Execute a user-confirmed command through the Windows shell."""
from __future__ import annotations

import subprocess
from typing import Any

MAX_OUTPUT_LENGTH = 4000
TRUNCATION_MARKER = "\n[...output troncato]"
CONFIRMATION_RESULT = "Ask the user for explicit confirmation"


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_LENGTH:
        return value
    return value[:MAX_OUTPUT_LENGTH] + TRUNCATION_MARKER


def terminal_run(parameters: dict | None = None, **_context: Any) -> dict[str, Any]:
    values = parameters or {}
    command = values.get("command")
    if not isinstance(command, str) or not command.strip():
        return {
            "stdout": "",
            "stderr": "command must be a non-empty string",
            "returncode": 2,
        }

    if values.get("confirmed") is not True:
        return {"result": CONFIRMATION_RESULT, "command": command}

    timeout = values.get("timeout", 30)
    cwd = values.get("cwd") or None
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "timeout", "returncode": -1}

    return {
        "stdout": _truncate(completed.stdout),
        "stderr": _truncate(completed.stderr),
        "returncode": completed.returncode,
    }


TOOL = {
    "name": "terminal_run",
    "description": (
        "Runs a shell command on Windows. Every command requires the user's explicit "
        "confirmation in a separate turn before it is executed."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {"type": "STRING"},
            "cwd": {"type": "STRING"},
            "timeout": {"type": "INTEGER", "default": 30},
        },
        "required": ["command"],
    },
    "risk_class": "write",
    "handler": terminal_run,
}

"""Execute a user-confirmed command through the guarded Terminal Agent."""
from __future__ import annotations

from typing import Any

from core.terminal_agent import (
    CommandBlocked,
    OverrideRequired,
    TerminalAgent,
    TerminalExecutionError,
)

MAX_OUTPUT_LENGTH = 4000
TRUNCATION_MARKER = "\n[...output troncato]"
CONFIRMATION_RESULT = "Ask the user for explicit confirmation"


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_LENGTH:
        return value
    return value[:MAX_OUTPUT_LENGTH] + TRUNCATION_MARKER


def terminal_run(
    parameters: dict | None = None,
    *,
    terminal_agent: TerminalAgent | None = None,
    **_context: Any,
) -> dict[str, Any]:
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

    mode = values.get("mode", "capture")
    if mode not in {"capture", "visible"}:
        return {
            "stdout": "",
            "stderr": "mode must be capture or visible",
            "returncode": 2,
        }
    timeout = values.get("timeout", 10)
    try:
        agent = terminal_agent or TerminalAgent(timeout_seconds=timeout)
        if mode == "visible":
            pid = agent.execute_visible(command)
            return {
                "stdout": "",
                "stderr": "",
                "returncode": 0,
                "pid": pid,
                "mode": "visible",
            }
        result = agent.execute(command)
    except OverrideRequired as exc:
        return {
            "stdout": "",
            "stderr": f"Blocked by terminal policy; explicit override required: {exc.result.reason}",
            "returncode": 126,
        }
    except (CommandBlocked, TerminalExecutionError, TypeError, ValueError) as exc:
        return {"stdout": "", "stderr": str(exc), "returncode": 126}

    return {
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "returncode": result.return_code,
    }


TOOL = {
    "name": "terminal_run",
    "description": (
        "Runs one allowlisted command through the guarded Terminal Agent. No shell "
        "operators or shell=True are used. Every command requires explicit user "
        "confirmation in a separate turn. Defaults to captured output in Jarvis chat; "
        "mode visible opens a new Windows console for the approved command. The YAML "
        "policy may still refuse the command even after confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "command": {"type": "STRING"},
            "mode": {
                "type": "STRING",
                "enum": ["capture", "visible"],
                "description": "capture returns output in chat; visible opens a new console.",
            },
            "timeout": {"type": "INTEGER", "default": 10},
        },
        "required": ["command"],
    },
    "risk_class": "write",
    "handler": terminal_run,
}

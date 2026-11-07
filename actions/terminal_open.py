"""Open a fresh, visible interactive Windows command prompt."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from core.guardrails import resolve_safe_path


def open_terminal(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    values = parameters or {}
    if values.get("confirmed") is not True:
        return "Ask the user for explicit confirmation before opening a terminal."
    if os.name != "nt":
        return "Opening an interactive terminal window is currently supported on Windows only."
    creation_flag = getattr(subprocess, "CREATE_NEW_CONSOLE", None)
    if creation_flag is None:
        return "Windows console creation is unavailable."
    raw_cwd = values.get("cwd")
    try:
        cwd = resolve_safe_path(raw_cwd) if raw_cwd else None
        if cwd is not None and not cwd.is_dir():
            return "The selected terminal working directory does not exist."
    except (OSError, TypeError, ValueError) as exc:
        return f"The selected terminal working directory is invalid: {exc}"
    try:
        process = subprocess.Popen(
            ["cmd.exe"],
            shell=False,
            cwd=cwd,
            creationflags=creation_flag,
            close_fds=True,
        )
    except OSError as exc:
        return f"Could not open the terminal ({type(exc).__name__})."
    return f"Opened a new interactive command prompt (PID {process.pid})."


TOOL = {
    "name": "terminal_open",
    "description": (
        "Opens a visible, interactive Windows command prompt without running a "
        "command. Requires explicit user confirmation. Do not use for command "
        "execution; use terminal_run, which is restricted by the terminal YAML policy."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "destructive",
    "handler": open_terminal,
}

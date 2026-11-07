"""Confirmation-gated wrapper around the existing visible terminal action."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from actions.terminal_open import open_terminal
from core import confirm
from core.actions_bridge import push_event
from core.audit_log import AuditLog


def run(parameters: dict[str, Any] | None = None, *, cwd: str | None = None, **_context):
    values = parameters or {}
    cwd = cwd if cwd is not None else values.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return {"ok": False, "error": "invalid_cwd", "reason": "cwd must be text or null."}

    active_confirmation = confirm.pending_title()
    if active_confirmation:
        return {
            "ok": False,
            "error": "confirmation_pending",
            "reason": f"Another confirmation is already pending: {active_confirmation}",
        }

    key = f"terminal-open-ext-{uuid.uuid4().hex}"

    def open_confirmed():
        result = open_terminal({"confirmed": True, "cwd": cwd})
        AuditLog(
            Path(__file__).resolve().parents[1] / "config" / "audit.jsonl"
        ).record(
            tool="terminal_open_ext",
            outcome="completed" if result.startswith("Opened") else "failed",
            scope="terminal",
            detail=result,
        )
        return str(result)

    message = confirm.request(
        key,
        "Aprire un nuovo terminale",
        "Windows Command Prompt",
        open_confirmed,
        on_cancel=lambda: push_event("terminal", {"event": "cancelled", "command": "open terminal"}),
    )
    if "[CONFIRMATION_PENDING]" not in message:
        push_event("terminal", {"event": "blocked", "command": "open terminal", "reason": message})
        return {"ok": False, "error": "confirmation_unavailable", "reason": message}
    return {"ok": False, "pending": True, "confirm_key": key}


TOOL = {
    "name": "terminal_open_ext",
    "description": "Open a visible Windows command prompt after explicit HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"cwd": {"type": "STRING", "nullable": True}},
    },
    "risk_class": "write",
    "handler": run,
}

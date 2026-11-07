"""Shared confirmation, foreground, and audit helpers for desktop actions."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from core.audit_log import AuditLog
from core.guardrails import redact_sensitive

_AUDIT = AuditLog(Path(__file__).resolve().parents[1] / "config" / "audit.jsonl")


def emit(event: str, **payload: Any) -> None:
    from core.actions_bridge import push_event

    push_event("computer_use", {"event": event, **payload})


def audit(tool: str, outcome: str, detail: str = "") -> None:
    _AUDIT.record(
        tool=tool,
        outcome=outcome,
        scope="computer_use",
        detail=redact_sensitive(detail)[:2000],
    )


def request_confirmed_input(tool: str, parameters: dict[str, Any]) -> dict[str, Any]:
    from core import confirm
    from core.computer_use import (
        execute_input,
        require_allowed_foreground,
        validate_input_request,
    )

    try:
        validate_input_request(parameters)
        expected_window, expected_process = require_allowed_foreground()
    except (OSError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
        reason = f"Computer input unavailable: {type(exc).__name__}: {exc}"
        emit("error", action=tool, status="stopped", reason=reason)
        audit(tool, "blocked", reason)
        return {"ok": False, "error": "foreground_blocked", "reason": reason}

    active_confirmation = confirm.pending_title()
    if active_confirmation:
        reason = f"Another confirmation is already pending: {active_confirmation}"
        emit("confirmation_pending", action=tool, status="idle", reason=reason)
        return {"ok": False, "error": "confirmation_pending", "reason": reason}

    operation = str(parameters.get("action", "computer action"))
    key = f"{tool}-{uuid.uuid4().hex}"

    def perform() -> str:
        from core.actions_bridge import wait_if_paused

        try:
            wait_if_paused()
            result = execute_input(
                {
                    **parameters,
                    "confirmed": True,
                    "_expected_window": expected_window,
                    "_expected_process": expected_process,
                }
            )
        except (
            LookupError,
            OSError,
            PermissionError,
            RuntimeError,
            TypeError,
            ValueError,
            InterruptedError,
        ) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            emit("error", action=operation, status="error", reason=reason)
            audit(tool, "failed", reason)
            return reason
        emit(
            "action_done",
            action=operation,
            status="idle",
            result=redact_sensitive(result),
        )
        audit(tool, "completed", str(result))
        return str(result.get("result", "Computer action completed."))

    message = confirm.request(
        key,
        f"Conferma azione Computer Use: {operation}",
        str(parameters),
        perform,
        on_cancel=lambda: (
            emit("cancelled", action=operation, status="idle"),
            audit(tool, "cancelled"),
        ),
    )
    if "[CONFIRMATION_PENDING]" not in message:
        emit("blocked", action=operation, status="idle", reason=message)
        audit(tool, "blocked", message)
        return {"ok": False, "error": "confirmation_unavailable", "reason": message}
    emit("action_pending", action=operation, status="running")
    audit(tool, "pending", operation)
    return {"ok": False, "pending": True, "confirm_key": key}


def request_confirmed_callback(
    tool: str,
    title: str,
    detail: str,
    callback,
) -> dict[str, Any]:
    from core import confirm

    active_confirmation = confirm.pending_title()
    if active_confirmation:
        reason = f"Another confirmation is already pending: {active_confirmation}"
        emit("confirmation_pending", action=tool, status="idle", reason=reason)
        return {"ok": False, "error": "confirmation_pending", "reason": reason}

    key = f"{tool}-{uuid.uuid4().hex}"

    def perform() -> str:
        from core.actions_bridge import wait_if_paused

        try:
            wait_if_paused()
            result = callback()
        except (
            LookupError,
            OSError,
            PermissionError,
            RuntimeError,
            TypeError,
            ValueError,
            InterruptedError,
        ) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            emit("error", action=tool, status="error", reason=reason)
            audit(tool, "failed", reason)
            return reason
        audit(tool, "completed", str(result))
        return str(result)

    message = confirm.request(
        key,
        title,
        detail,
        perform,
        on_cancel=lambda: (
            emit("cancelled", action=tool, status="idle"),
            audit(tool, "cancelled"),
        ),
    )
    if "[CONFIRMATION_PENDING]" not in message:
        emit("blocked", action=tool, status="idle", reason=message)
        audit(tool, "blocked", message)
        return {"ok": False, "error": "confirmation_unavailable", "reason": message}
    emit("action_pending", action=tool, status="running")
    audit(tool, "pending", detail)
    return {"ok": False, "pending": True, "confirm_key": key}

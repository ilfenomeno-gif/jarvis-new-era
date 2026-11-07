"""Capture a screenshot for the Computer Use HUD after confirmation."""

from __future__ import annotations

import base64
from io import BytesIO

from core.computer_action_support import emit, request_confirmed_callback


def run(parameters=None, **_context):
    from core.computer_use import (
        capture_screen,
        emergency_stop_triggered,
        require_allowed_foreground,
    )

    try:
        require_allowed_foreground()
        if emergency_stop_triggered():
            return {"ok": False, "error": "stopped", "reason": "Computer Use emergency stop is active."}
    except (OSError, PermissionError, RuntimeError) as exc:
        reason = f"Screenshot unavailable: {type(exc).__name__}: {exc}"
        emit("error", status="stopped", reason=reason)
        return {"ok": False, "error": "capture_unavailable", "reason": reason}

    result: dict = {}

    def capture() -> str:
        image, monitor = capture_screen()
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        result.update({"base64": encoded, "status": "idle", "monitor": monitor})
        emit("screenshot", **result)
        return "Screenshot captured and sent to the Computer Use widget."

    pending = request_confirmed_callback(
        "computer_screenshot",
        "Conferma screenshot",
        "Catturare e mostrare lo schermo nel pannello Computer Use.",
        capture,
    )
    if pending.get("pending"):
        return pending
    return pending


TOOL = {
    "name": "computer_screenshot",
    "description": "Capture and display a screenshot after HUD confirmation.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "write",
    "handler": run,
}

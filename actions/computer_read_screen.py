"""Read visible desktop text locally after explicit user confirmation."""

from __future__ import annotations

import json
from typing import Any


def read_screen(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    values = parameters or {}
    if values.get("confirmed") is not True:
        return json.dumps(
            {"ok": False, "error": "explicit_confirmation_required"},
            ensure_ascii=False,
        )

    from core.computer_action_support import audit
    from core.computer_use import (
        capture_screen,
        emergency_stop_triggered,
        ocr_screen,
        require_allowed_foreground,
    )

    if emergency_stop_triggered():
        return json.dumps({"ok": False, "error": "computer_use_stopped"})

    window, process = require_allowed_foreground()
    image, monitor = capture_screen()
    words = ocr_screen(image=image, monitor=monitor)
    current_window, current_process = require_allowed_foreground()
    if (current_window, current_process) != (window, process):
        return json.dumps(
            {"ok": False, "error": "foreground_changed_during_capture"},
            ensure_ascii=False,
        )

    text = " ".join(item["text"] for item in words)
    truncated = len(text) > 6000
    audit("computer_read_screen", "completed", f"process={process}; words={len(words)}")
    return json.dumps(
        {
            "ok": True,
            "process": process,
            "text": text[:6000],
            "word_count": len(words),
            "truncated": truncated,
        },
        ensure_ascii=False,
    )


TOOL = {
    "name": "computer_read_screen",
    "description": (
        "Read text visible on the current allowlisted Windows screen using local OCR. "
        "Requires explicit user confirmation; returns at most 6000 characters and "
        "does not save a screenshot or OCR text."
    ),
    "parameters": {"type": "OBJECT", "properties": {}},
    "risk_class": "destructive",
    "handler": read_screen,
}

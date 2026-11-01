"""Deterministic local screen perception and explicitly confirmed input."""
from __future__ import annotations

import json
from typing import Any

from core import computer_use


def computer_perception(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    values = parameters or {}
    action = str(values.get("action", "")).strip().casefold()
    if action == "capture":
        result = computer_use.screen_capture_metadata()
    elif action == "ocr":
        language = values.get("language", "eng")
        confidence = values.get("min_confidence", 45)
        if not isinstance(language, str) or not language.strip():
            raise ValueError("language must be a non-empty Tesseract language code.")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError("min_confidence must be a number from 0 to 100.")
        if not 0 <= confidence <= 100:
            raise ValueError("min_confidence must be a number from 0 to 100.")
        result = {"words": computer_use.ocr_screen(language, float(confidence))}
    elif action == "uia":
        result = computer_use.active_window_tree()
    elif action == "wait_for_change":
        result = computer_use.wait_for_screen_change(
            initial_hash=values.get("initial_hash"),
            timeout=values.get("timeout", 10),
            poll_interval=values.get("poll_interval", 0.5),
            threshold=values.get("threshold", 0.08),
        )
    else:
        raise ValueError("action must be capture, ocr, uia, or wait_for_change.")
    return json.dumps(result, ensure_ascii=False)


TOOL = {
    "name": "computer_perception",
    "description": (
        "Local, read-only screen tools: capture metadata and a perceptual hash, "
        "perform on-device OCR, inspect the active window through UI Automation, "
        "or wait for a screen change. Screenshots are not saved or uploaded; returned "
        "text is provided to the currently selected model."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["capture", "ocr", "uia", "wait_for_change"],
            },
            "language": {"type": "STRING", "default": "eng"},
            "min_confidence": {"type": "NUMBER", "default": 45},
            "initial_hash": {"type": "STRING"},
            "timeout": {"type": "NUMBER", "default": 10},
            "poll_interval": {"type": "NUMBER", "default": 0.5},
            "threshold": {"type": "NUMBER", "default": 0.08},
        },
        "required": ["action"],
    },
    "risk_class": "read",
    "handler": computer_perception,
}

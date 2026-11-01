"""Single-step desktop input guarded by explicit user confirmation."""
from __future__ import annotations

import json
from typing import Any

from core.computer_use import execute_input


def computer_input(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    return json.dumps(execute_input(parameters or {}), ensure_ascii=False)


TOOL = {
    "name": "computer_input",
    "description": (
        "Perform exactly one mouse or keyboard action in the focused, allowlisted "
        "Windows app. Every action requires explicit user confirmation in a separate "
        "turn. Ctrl+Alt+Esc is the emergency stop. Never chain actions."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": [
                    "click", "click_text", "double_click", "drag", "move",
                    "press", "hotkey", "scroll", "type", "type_text",
                ],
            },
            "x": {"type": "INTEGER"},
            "y": {"type": "INTEGER"},
            "x1": {"type": "INTEGER"},
            "y1": {"type": "INTEGER"},
            "x2": {"type": "INTEGER"},
            "y2": {"type": "INTEGER"},
            "target": {"type": "STRING"},
            "key": {"type": "STRING"},
            "keys": {"type": "STRING"},
            "direction": {"type": "STRING", "enum": ["up", "down"]},
            "amount": {"type": "INTEGER", "default": 1},
            "text": {"type": "STRING"},
        },
        "required": ["action"],
    },
    "risk_class": "destructive",
    "handler": computer_input,
}

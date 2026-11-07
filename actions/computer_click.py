"""Confirmation-gated mouse click."""

from core.computer_action_support import request_confirmed_input


def run(parameters=None, *, x=None, y=None, button="left", **_context):
    values = parameters or {}
    x = x if x is not None else values.get("x")
    y = y if y is not None else values.get("y")
    button = values.get("button", button)
    if button not in {"left", "right", "middle"}:
        return {"ok": False, "error": "invalid_button", "reason": "button must be left, right, or middle."}
    return request_confirmed_input(
        "computer_click",
        {"action": "click", "x": x, "y": y, "button": button},
    )


TOOL = {
    "name": "computer_click",
    "description": "Click a screen position after explicit HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "x": {"type": "INTEGER"},
            "y": {"type": "INTEGER"},
            "button": {"type": "STRING", "enum": ["left", "right", "middle"], "default": "left"},
        },
        "required": ["x", "y"],
    },
    "risk_class": "destructive",
    "handler": run,
}

"""Confirmation-gated mouse movement."""

from core.computer_action_support import request_confirmed_input


def run(parameters=None, *, x=None, y=None, **_context):
    values = parameters or {}
    x = x if x is not None else values.get("x")
    y = y if y is not None else values.get("y")
    return request_confirmed_input("computer_move", {"action": "move", "x": x, "y": y})


TOOL = {
    "name": "computer_move",
    "description": "Move the mouse to a screen position; always requires explicit HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"x": {"type": "INTEGER"}, "y": {"type": "INTEGER"}},
        "required": ["x", "y"],
    },
    "risk_class": "destructive",
    "handler": run,
}

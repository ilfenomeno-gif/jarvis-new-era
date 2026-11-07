"""Confirmation-gated text entry."""

from core.computer_action_support import request_confirmed_input


def run(parameters=None, *, text=None, interval=0, **_context):
    values = parameters or {}
    text = text if text is not None else values.get("text")
    interval = values.get("interval", interval)
    return request_confirmed_input(
        "computer_type",
        {"action": "type", "text": text, "interval": interval},
    )


TOOL = {
    "name": "computer_type",
    "description": "Type text into the allowlisted foreground application after HUD confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "text": {"type": "STRING"},
            "interval": {"type": "NUMBER", "default": 0},
        },
        "required": ["text"],
    },
    "risk_class": "destructive",
    "handler": run,
}

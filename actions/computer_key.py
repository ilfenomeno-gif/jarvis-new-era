"""Confirmation-gated key press."""

from core.computer_action_support import request_confirmed_input


def run(parameters=None, *, key=None, **_context):
    values = parameters or {}
    key = key if key is not None else values.get("key")
    return request_confirmed_input("computer_key", {"action": "press", "key": key})


TOOL = {
    "name": "computer_key",
    "description": "Press one supported key in the allowlisted foreground application after confirmation.",
    "parameters": {
        "type": "OBJECT",
        "properties": {"key": {"type": "STRING"}},
        "required": ["key"],
    },
    "risk_class": "destructive",
    "handler": run,
}

"""Voice action for battery charge and charging state."""
from actions._system_pulse_action_helpers import read_metrics


def check_battery(parameters: dict) -> str:
    return read_metrics(("battery_percent", "battery_plugged", "battery_seconds_left"))


TOOL = {
    "name": "check_battery",
    "description": "Reports battery charge, charging state, and estimated time remaining.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_battery,
}

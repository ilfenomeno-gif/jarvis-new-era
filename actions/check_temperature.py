"""Voice action for available CPU temperature metrics."""
from actions._system_pulse_action_helpers import read_metrics


def check_temperature(parameters: dict) -> str:
    return read_metrics(("temperature_celsius",))


TOOL = {
    "name": "check_temperature",
    "description": "Reports CPU temperature when supported by the device and platform.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_temperature,
}

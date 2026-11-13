"""Voice action returning a privacy-filtered system overview."""
from actions._system_pulse_action_helpers import read_metrics


def check_system(parameters: dict) -> str:
    return read_metrics()


TOOL = {
    "name": "check_system",
    "description": "Reports overall system health and recent 60-sample trends.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_system,
}

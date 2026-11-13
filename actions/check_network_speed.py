"""Voice action for aggregate network transfer rates."""
from actions._system_pulse_action_helpers import read_metrics


def check_network_speed(parameters: dict) -> str:
    return read_metrics(("network_down_mb_s", "network_up_mb_s"))


TOOL = {
    "name": "check_network_speed",
    "description": "Reports aggregate download and upload speeds in decimal MB/s.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_network_speed,
}

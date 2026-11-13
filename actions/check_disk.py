"""Voice action for disk capacity."""
from actions._system_pulse_action_helpers import read_metrics


def check_disk(parameters: dict) -> str:
    return read_metrics((
        "disk_count", "disk_total_bytes", "disk_used_bytes", "disk_free_bytes",
        "disk_percent", "disks",
    ))


TOOL = {
    "name": "check_disk",
    "description": "Reports capacity and free space for available drives without paths.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_disk,
}

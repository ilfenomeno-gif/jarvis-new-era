"""Voice action for memory utilization."""
from actions._system_pulse_action_helpers import read_metrics


def check_ram(parameters: dict) -> str:
    return read_metrics(("memory_percent", "memory_used_bytes", "memory_total_bytes"))


TOOL = {
    "name": "check_ram",
    "description": "Reports RAM usage, total capacity, and current utilization.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_ram,
}

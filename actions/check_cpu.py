"""Voice action for total and per-core CPU utilization."""
from actions._system_pulse_action_helpers import read_metrics


def check_cpu(parameters: dict) -> str:
    return read_metrics((
        "cpu_percent", "cpu_cores_percent", "cpu_threshold_percent",
        "cpu_sustain_seconds", "cpu_sustained", "cpu_sustained_seconds",
        "trend_60",
    ))


TOOL = {
    "name": "check_cpu",
    "description": "Reports total and per-core CPU use and its sustained-load trend.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": check_cpu,
}

"""Read-only action exposing the local system-pulse snapshot."""
from __future__ import annotations

from actions._system_pulse_action_helpers import read_metrics


def system_pulse(parameters: dict) -> str:
    """Return the snapshot of the already-running hub pulse module."""
    return read_metrics()


TOOL = {
    "name": "system_pulse",
    "description": (
        "Returns a privacy-filtered snapshot of CPU, memory, disk, battery, temperature, "
        "network, optional GPU, uptime, process count, and recent metric trends."
    ),
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": system_pulse,
}

"""Return processes exceeding requested CPU or RAM thresholds."""

import json

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def monitor_hogs(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    try:
        return json.dumps(
            process_core.monitor_hogs(
                cpu_threshold=parameters.get("cpu_threshold", 80),
                ram_threshold=parameters.get("ram_threshold", 80),
                limit=parameters.get("limit", 200),
            ),
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return "Invalid thresholds; use CPU/RAM percentages from 0 to 100 and limit 1–200."


TOOL = {
    "name": "monitor_hogs",
    "description": (
        "Find processes at or above CPU/RAM percentage thresholds (defaults: 80%). "
        "Only non-identifying process metrics are returned."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "cpu_threshold": {"type": "NUMBER", "description": "CPU percentage, 0–100."},
            "ram_threshold": {"type": "NUMBER", "description": "RAM percentage, 0–100."},
            "limit": {"type": "INTEGER", "description": "Maximum entries, 1–200."},
        },
        "required": [],
    },
    "handler": monitor_hogs,
}

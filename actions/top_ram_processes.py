"""List RAM-heavy processes."""

import json

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def top_ram_processes(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    try:
        rows = process_core.list_top_processes(
            limit=parameters.get("limit", 20),
            sort_by="ram",
        )
        return json.dumps(rows, separators=(",", ":"))
    except (TypeError, ValueError):
        return "Invalid limit; use an integer from 1 to 200."


TOOL = {
    "name": "top_ram_processes",
    "description": (
        "List processes with highest RAM percentages. Returns only PID, opaque "
        "reference, status, metrics, and protection state; no names or paths."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "limit": {"type": "INTEGER", "description": "Maximum entries, 1–200."},
        },
        "required": [],
    },
    "handler": top_ram_processes,
}

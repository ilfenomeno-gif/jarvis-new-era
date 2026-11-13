"""List process resource metrics without exposing personal process details."""

from __future__ import annotations

import json

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def list_processes(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    try:
        limit = parameters.get("limit", 100)
        sort_by = str(parameters.get("sort_by", "cpu")).strip().lower()
        rows = process_core.list_top_processes(limit=limit, sort_by=sort_by)
        return json.dumps(rows, separators=(",", ":"))
    except (TypeError, ValueError):
        return "Invalid process-list arguments; use limit 1–200 and sort_by cpu or ram."


TOOL = {
    "name": "list_processes",
    "description": (
        "List process IDs, opaque references, status, CPU/RAM percentages, and a "
        "protected flag. Results never include process names, command lines, paths, "
        "usernames, window titles, or IP addresses. Sort by cpu or ram."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "limit": {"type": "INTEGER", "description": "Maximum entries, 1–200."},
            "sort_by": {
                "type": "STRING",
                "enum": ["cpu", "ram"],
                "description": "Sort order, highest first.",
            },
        },
        "required": [],
    },
    "handler": list_processes,
}

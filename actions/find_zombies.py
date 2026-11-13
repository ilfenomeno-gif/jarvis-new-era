"""Find zombie and likely orphaned processes using non-identifying fields."""

import json

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def find_zombies(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    try:
        return json.dumps(
            process_core.find_zombies(limit=parameters.get("limit", 200)),
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return "Invalid limit; use an integer from 1 to 200."


TOOL = {
    "name": "find_zombies",
    "description": (
        "Find zombie processes and likely orphans. Orphan detection is a best-effort "
        "parent-PID heuristic; process names and paths are not returned."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "limit": {"type": "INTEGER", "description": "Maximum entries, 1–200."},
        },
        "required": [],
    },
    "handler": find_zombies,
}

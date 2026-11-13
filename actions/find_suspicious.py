"""Find suspicious process indicators without returning paths or names."""

import json

from actions._process_master_support import UNAVAILABLE, available
from core import process_master as process_core


def find_suspicious(parameters: dict, **_ignored) -> str:
    parameters = parameters or {}
    if not available():
        return UNAVAILABLE
    try:
        return json.dumps(
            process_core.find_suspicious(limit=parameters.get("limit", 200)),
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return "Invalid limit; use an integer from 1 to 200."


TOOL = {
    "name": "find_suspicious",
    "description": (
        "Flag process names or executable locations containing Temp markers and "
        "unsigned PE files when detectable. Signature checks are best effort and "
        "do not validate trust; names and paths are never returned."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "limit": {"type": "INTEGER", "description": "Maximum entries, 1–200."},
        },
        "required": [],
    },
    "handler": find_suspicious,
}

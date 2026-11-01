"""Connector catalogue status (read-only projection of the registry)."""
from __future__ import annotations

import json

from core.jarvis_runtime import get_runtime


def connectors_status(parameters: dict) -> str:
    try:
        runtime = get_runtime()
        return json.dumps({"connectors": runtime.connectors.view(),
                           "skills": runtime.skills.view()}, ensure_ascii=False)
    except Exception as exc:
        return f"Connectors are not available: {exc}"


TOOL = {
    "name": "connectors_status",
    "description": "Lists connectors (status, scopes, tools) and skills (status) known to Jarvis.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": connectors_status,
}

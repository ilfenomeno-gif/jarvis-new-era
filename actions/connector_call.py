"""Calls a tool exposed by a connected connector, with scope checks and audit."""
from __future__ import annotations

import json

from core.connectors import ConnectorError
from core.jarvis_runtime import get_runtime


def connector_call(parameters: dict) -> str:
    tool = str(parameters.get("tool", "")).strip()
    if not tool:
        return "Specify the connector tool name, e.g. 'gmail.search'."
    try:
        arguments = json.loads(parameters.get("arguments_json") or "{}")
    except json.JSONDecodeError:
        return "arguments_json must be a valid JSON object."
    if not isinstance(arguments, dict):
        return "arguments_json must be a JSON object."
    try:
        return str(get_runtime().connectors.call_tool(tool, arguments, skill=parameters.get("skill")))
    except ConnectorError as exc:
        return f"Connector call refused: {exc}"
    except Exception as exc:
        return f"Connector call failed: {exc}"


TOOL = {
    "name": "connector_call",
    "description": (
        "Calls a namespaced connector tool (for example 'calendar.list_events'). "
        "Only works for connected connectors with the needed scope granted. "
        "For gmail.search, arguments_json accepts query and max_results; "
        "use query '-in:sent' and max_results 1 for the latest received email. "
        "For GitHub repository searches, provide a non-empty query to "
        "github.search_repositories; for repositories owned by the authenticated "
        "account, use github_user_repositories instead of search_repositories."),
    "risk_class": "write",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "tool": {"type": "STRING", "description": "Namespaced tool, e.g. gmail.search"},
            "arguments_json": {"type": "STRING", "description": "Tool arguments as a JSON object string"},
            "skill": {"type": "STRING", "description": "Skill that is running, if any"},
        },
        "required": ["tool"],
    },
    "handler": connector_call,
}

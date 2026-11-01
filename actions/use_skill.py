"""Skill entry point: pick the matching skill and return its procedure."""
from __future__ import annotations

from core.jarvis_runtime import get_runtime
from core.skills import SkillError


def use_skill(parameters: dict) -> str:
    request = str(parameters.get("request", "")).strip()
    if not request:
        return "Describe what the user asked for in 'request'."
    try:
        route, activation = get_runtime().router.prepare(request)
    except SkillError as exc:
        return f"Skill unavailable: {exc}"
    except Exception as exc:
        return f"Skills are not available: {exc}"
    if activation is None:
        return f"No matching skill (intent: {route.intent}). Proceed with the normal tools."
    if not activation.ready:
        return ("Skill '" + activation.skill + "' needs connectors first: "
                + "; ".join(activation.missing) + ". Ask the user to connect them.")
    return f"Follow this procedure (skill '{activation.skill}'):\n{activation.body}"


TOOL = {
    "name": "use_skill",
    "description": (
        "Looks up a declarative skill (a stored procedure) that matches the user's request "
        "and returns its steps. Call it before multi-step requests such as briefings."),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {"request": {"type": "STRING", "description": "The user's request, verbatim."}},
        "required": ["request"],
    },
    "handler": use_skill,
}

"""Session-approved, bounded agentic desktop workflow."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from core.agent_loop import AgentLoop, resolve_max_steps


def agent_loop(parameters: dict[str, Any] | None = None, **_context: Any) -> str:
    values = parameters or {}
    goal = values.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("goal must be a non-empty string.")
    maximum = resolve_max_steps(values.get("max_steps"))
    session_approved = values.get("_session_approved") is True
    loop = AgentLoop(
        max_steps=maximum,
        confirm_session=lambda _prompt: session_approved,
    )
    result = asyncio.run(loop.run(goal))
    return json.dumps(result, ensure_ascii=False)


TOOL = {
    "name": "agent_loop",
    "description": (
        "Work toward a multi-step desktop goal using screen perception and "
        "single-step mouse or keyboard actions. Before running, ask the user to "
        "approve the goal and maximum number of actions. Screen images are sent "
        "to Gemini cloud for planning. Stop on Ctrl+Alt+Esc, focus changes, "
        "non-allowlisted foreground apps, repeated unchanged screens, or the "
        "configured hard action limit."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {"type": "STRING"},
            "max_steps": {
                "type": "INTEGER",
                "description": "Maximum number of actions, capped by JARVIS_AGENT_MAX_STEPS.",
            },
        },
        "required": ["goal"],
    },
    "risk_class": "write",
    "handler": agent_loop,
}

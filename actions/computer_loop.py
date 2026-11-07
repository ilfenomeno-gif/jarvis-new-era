"""Expose the opt-in unified terminal and browser computer-use loop."""
from __future__ import annotations

import json
import os
from typing import Any


def computer_loop(
    parameters: dict[str, Any] | None = None,
    *,
    computer_loop: Any = None,
    **_context: Any,
) -> str:
    if os.environ.get("JARVIS_COMPUTER_LOOP", "0") != "1":
        return (
            "The unified Computer Use loop is disabled. Existing terminal_run "
            "and browser_automation actions remain available."
        )
    values = parameters or {}
    goal = values.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        return "A non-empty goal is required."
    if computer_loop is None:
        raise RuntimeError(
            "JARVIS_COMPUTER_LOOP is enabled but the loop service was not initialized."
        )
    workspace = values.get("workspace")
    harness_runtime = _context.get("harness_runtime")
    if harness_runtime is not None:
        from core.harness.session import HarnessSession

        result = harness_runtime.run(HarnessSession(
            agent="computer_use_loop",
            goal=goal.strip(),
            artifacts=[{"workspace": workspace}] if workspace else [],
            status="approved" if values.get("confirmed") is True else "created",
        ))
        return json.dumps(result.to_dict(), ensure_ascii=False)
    result = computer_loop.run(goal, workspace=workspace)
    return json.dumps(result.to_dict(), ensure_ascii=False)


TOOL = {
    "name": "computer_use_loop",
    "description": (
        "Plan, perform, verify, remember, and if needed re-plan bounded terminal "
        "or browser DOM tasks. The unified loop is opt-in via "
        "JARVIS_COMPUTER_LOOP=1; when off, existing actions remain available. "
        "Browser clicks/submissions and terminal policy overrides require approval "
        "through the confirmation banner."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {"type": "STRING"},
            "workspace": {
                "type": "STRING",
                "description": (
                    "Existing directory that bounds filesystem operations and screenshots."
                ),
            },
        },
        "required": ["goal"],
    },
    "risk_class": "write",
    "handler": computer_loop,
}

"""Play Subway Surfers by analyzing obstacles in the integrated browser."""
from __future__ import annotations

import json
from typing import Any

from core.subway_surfer import play_subway_surfer as run_game


def subway_surfer(
    parameters: dict[str, Any] | None = None,
    *,
    player: Any = None,
    **_context: Any,
) -> str:
    values = parameters or {}
    result = run_game(
        player,
        values.get("max_actions"),
        key_scheme=values.get("key_scheme", "arrows"),
    )
    return json.dumps(result, ensure_ascii=False)


TOOL = {
    "name": "subway_surfer",
    "description": (
        "Play Subway Surfers autonomously in Jarvis's currently open integrated "
        "browser page. Before every move, Gemini identifies the runner lane and "
        "visible obstacles by lane, type, distance and confidence from the game "
        "frame screenshot/HTML, then selects a move. Unsafe moves toward a "
        "reported nearby obstacle are rejected or redirected to a reported-safe "
        "adjacent lane. Stale decisions (>3 seconds) are discarded without input. "
        "Event-triggered strategic review is combined with reactive safety checks, "
        "run-scoped state/action memory, post-move verification, and one fresh "
        "re-observation when visual confidence is below 0.75. "
        "The game must already be open in Jarvis's browser. "
        "Screenshots and DOM text are sent to Gemini cloud. Stops on uncertain "
        "vision, after max_actions (default 20, hard maximum 60), or Ctrl+Alt+Esc. "
        "key_scheme selects arrows or WASD (arrows by default). Never navigates "
        "to a site or controls another window."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "max_actions": {
                "type": "INTEGER",
                "description": "Maximum gameplay decisions, from 1 to 60 (default 20).",
            },
            "key_scheme": {
                "type": "STRING",
                "enum": ["arrows", "wasd"],
                "description": "Use arrow keys or WASD (default arrows).",
            },
        },
        "required": [],
    },
    "risk_class": "write",
    "handler": subway_surfer,
}

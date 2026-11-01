"""Lets Jarvis drive the HUD 3D map (open a system, run a scenario, tour, …).

The HUD (core/jarvis_hud.html, the JARVIS 3D map) listens for "command" events
from the HudBridge. This action is how the MODEL asks for them — so Jarvis can
use its own HTML UI instead of the user clicking.
"""
from __future__ import annotations

from core import outcome

# Systems on the 3D map (ids in jarvis_hud.html).
_SYSTEMS = (
    "core", "router", "actions", "guard", "hud", "memory", "task", "plugins",
    "skill", "conn", "browser", "vision", "gen3d", "gev", "dash", "vsc", "astral",
)
# Demo scenarios on the 3D map.
_SCENARIOS = (
    "Apri Netflix", "Spegni il PC", "Task multi-fase", "Genera modello 3D",
    "Interroga GEV", "Usa una skill",
)
_ACTIONS = ("open_system", "pick", "tour", "run", "say", "set_task", "top_view", "reveal")


def hud_control(parameters: dict, player=None, **_ignored) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    if action not in _ACTIONS:
        return outcome.failed("hud_control", f"unknown action {action!r}",
                              available=", ".join(_ACTIONS))
    command = getattr(player, "hud_command", None) if player is not None else None
    if not callable(command):
        return outcome.failed("hud_control", "the HUD is not available")

    if action in ("open_system", "pick"):
        sys_id = str(params.get("system", "")).strip().lower()
        if sys_id not in _SYSTEMS:
            return outcome.failed("hud_control", f"unknown system {sys_id!r}",
                                  available=", ".join(_SYSTEMS))
        command(action, id=sys_id)
        return outcome.done("hud_control", action=action, system=sys_id)

    if action == "tour":
        command("tour")
        return outcome.done("hud_control", action="tour")

    if action == "run":
        scenario = str(params.get("scenario", "")).strip()
        if scenario not in _SCENARIOS:
            return outcome.failed("hud_control", f"unknown scenario {scenario!r}",
                                  available=", ".join(_SCENARIOS))
        command("run", scenario=scenario)
        return outcome.done("hud_control", action="run", scenario=scenario)

    if action == "say":
        text = str(params.get("text", "")).strip()
        if not text:
            return outcome.failed("hud_control", "empty text")
        command("say", text=text)
        return outcome.done("hud_control", action="say")

    # set_task
    if action == "set_task":
        progress = params.get("progress", 0)
        status = str(params.get("status", "idle"))
        command("set_task", progress=progress, status=status)
        return outcome.done("hud_control", action="set_task", status=status)

    # top_view / reveal (umanoid) — optional on=true|false to force, omit to toggle
    on = params.get("on")
    kwargs = {} if not isinstance(on, bool) else {"on": on}
    command(action, **kwargs)
    return outcome.done("hud_control", action=action)


TOOL = {
    "name": "hud_control",
    "description": (
        "Drives the JARVIS 3D map HUD. action=open_system|pick with system="
        + "|".join(_SYSTEMS)
        + " opens/highlights that module. action=tour starts the guided tour. "
        "action=run with scenario=" + "|".join(_SCENARIOS) + " plays a demo scenario. "
        "action=say with text=… shows a message on the HUD. action=set_task with "
        "progress=0-100 and status=… updates the TaskRunner bar. action=top_view "
        "(optional on=true|false) toggles the top-down view. action=reveal "
        "(optional on=true|false) shows/hides the humanoid (Mira). Use this to show "
        "the user a system or scenario on the 3D map."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": ", ".join(_ACTIONS)},
            "system": {"type": "STRING", "description": ", ".join(_SYSTEMS)},
            "scenario": {"type": "STRING", "description": ", ".join(_SCENARIOS)},
            "text": {"type": "STRING", "description": "Text for action=say."},
            "progress": {"type": "NUMBER", "description": "0-100 for action=set_task."},
            "status": {"type": "STRING", "description": "Status for action=set_task."},
            "on": {"type": "BOOLEAN", "description": "Optional on/off for top_view and reveal."},
        },
        "required": ["action"],
    },
    "handler": hud_control,
}

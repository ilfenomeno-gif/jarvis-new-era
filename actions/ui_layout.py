"""Lets Jarvis change the HUD layout. UI only: no data is read or written."""

import json

from core.ui_panels import ALIASES, DOCKS, PANELS, WORKSPACES, resolve

_MODES = (
    "focus_on", "focus_off", "focus_toggle", "toggle_panel", "float_panel",
    "restore_layout", "workspace", "status",
)
_NAMES = ", ".join(PANELS + tuple(ALIASES))


def ui_layout(parameters: dict, player=None, **_ignored) -> str:
    params = parameters or {}
    mode = str(params.get("mode", "")).strip().lower()
    if mode not in _MODES:
        return f"Unknown mode '{mode}'. Use one of: {', '.join(_MODES)}."
    if player is None or not hasattr(player, "set_focus_mode"):
        return "The interface is not available."

    if mode in ("focus_on", "focus_off", "focus_toggle"):
        active = {
            "focus_on": True,
            "focus_off": False,
            "focus_toggle": not player.focus_mode,
        }[mode]
        player.set_focus_mode(active)
        return "Focus mode on: panels hidden." if active else "Focus mode off: panels back where they were."

    if mode == "status":
        return json.dumps(player.panel_status())

    if mode == "workspace":
        name = str(params.get("workspace", "")).strip().lower()
        if name not in WORKSPACES:
            return f"Unknown workspace '{name}'. Use one of: {', '.join(WORKSPACES)}."
        player.apply_workspace(name)
        return f"Workspace '{name}' applied."

    if mode == "restore_layout":
        player.restore_layout()
        return "Layout restored: all panels shown and docked in their original place."

    try:
        names = resolve(params.get("panel", ""))
    except ValueError as exc:
        return str(exc)

    if mode == "float_panel":
        if not hasattr(player, "float_panel"):
            return "The interface is not available."
        if any(name not in DOCKS for name in names):
            return f"Only these panels can be detached: {', '.join(DOCKS)}."
        floating = params.get("floating")
        if not isinstance(floating, bool):
            floating = None
        player.float_panel(params.get("panel"), floating)
        verb = "toggled between docked and floating" if floating is None else (
            "detached into a floating window" if floating else "docked again")
        return f"Panel '{params.get('panel')}' {verb}."

    visible = params.get("visible")
    if not isinstance(visible, bool):
        panels = player.panel_status()["panels"]
        visible = not all(panels[name] for name in names)
    player.set_panel_visible(params.get("panel"), visible)
    return f"Panel '{params.get('panel')}' {'shown' if visible else 'hidden'}."


TOOL = {
    "name": "ui_layout",
    "description": (
        "Changes the HUD layout. mode=focus_on/focus_off/focus_toggle hides the panels "
        "or brings them back where they were. mode=workspace with workspace=full|focus|"
        "coding|recon applies a preset. mode=toggle_panel with panel=activity_log|"
        "controls|input|header|content|footer (aliases: log, left, right) and optional "
        "visible=true|false shows or hides one panel (the log can be closed and reopened). "
        "mode=float_panel with panel=activity_log|controls|input detaches it into its own "
        "window (floating=false docks it back, omit to toggle). mode=restore_layout resets "
        "every panel to its original position. mode=status reports what is visible and floating."
    ),
    "risk_class": "read",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "mode": {"type": "STRING", "description": ", ".join(_MODES)},
            "workspace": {"type": "STRING", "description": ", ".join(WORKSPACES)},
            "panel": {"type": "STRING", "description": _NAMES},
            "visible": {"type": "BOOLEAN", "description": "Omit to toggle."},
            "floating": {"type": "BOOLEAN", "description": "float_panel only. Omit to toggle."},
        },
        "required": ["mode"],
    },
    "handler": ui_layout,
}

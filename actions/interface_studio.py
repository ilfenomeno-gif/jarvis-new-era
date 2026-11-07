"""Lets Jarvis edit its own HUD workspace and visual annotations."""
from __future__ import annotations

import json
import math
import re
from typing import Any


_ACTIONS = {"edit_mode", "panel", "label", "board", "camera", "scene", "html"}
_PANELS = {"header", "left", "info", "bar"}
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,39}\Z")
_COLOR = re.compile(r"(?:#[0-9a-fA-F]{6}|cyan|amber|white|red|green)\Z")
_LABEL_OPS = {"add", "remove", "clear"}
_BOARD_OPS = {"show", "hide", "draw", "clear", "add"}
_BOARD_SHAPES = {"text", "line", "arrow", "rect"}
_SCENE_OPS = {"save", "load", "delete", "list"}
_HTML_OPS = {"show", "close"}
_MAX_HTML_BYTES = 100_000


def _number(params: dict[str, Any], name: str, *, low: float, high: float) -> float:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    return value


def _safe_id(value: Any, name: str = "id") -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be 1-40 letters, numbers, '_' or '-'.")
    return value


def _color(params: dict[str, Any]) -> str:
    value = params.get("color", "cyan")
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ValueError("color must be a supported name or a six-digit hex color.")
    return value


def interface_studio(parameters: dict[str, Any] | None = None, player=None, **_ignored) -> str:
    params = parameters or {}
    action = str(params.get("action", "")).strip().lower()
    if action not in _ACTIONS:
        return f"Unknown interface_studio action {action!r}; use {', '.join(sorted(_ACTIONS))}."
    command = getattr(player, "hud_command", None) if player is not None else None
    if not callable(command):
        return "Jarvis's visual interface is unavailable."

    try:
        if action == "edit_mode":
            enabled = params.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be true or false.")
            command("studio_edit_mode", enabled=enabled)
            return json.dumps({"status": "done", "action": action, "enabled": enabled})

        if action == "panel":
            panel = params.get("panel")
            if panel not in _PANELS:
                raise ValueError(f"panel must be one of {', '.join(sorted(_PANELS))}.")
            payload: dict[str, Any] = {"panel": panel}
            visible = params.get("visible")
            if visible is not None:
                if not isinstance(visible, bool):
                    raise ValueError("visible must be true or false.")
                payload["visible"] = visible
            for name in ("x", "y"):
                if name in params:
                    payload[name] = _number(params, name, low=0, high=10000)
            for name in ("width", "height"):
                if name in params:
                    payload[name] = _number(params, name, low=160, high=2400)
            if not any(name in payload for name in ("visible", "x", "y", "width", "height")):
                raise ValueError("Specify visible, position (x/y), or size (width/height).")
            command("studio_panel", **payload)
            return json.dumps({"status": "done", "action": action, **payload})

        if action == "label":
            operation = params.get("operation")
            if operation not in _LABEL_OPS:
                raise ValueError(f"operation must be one of {', '.join(sorted(_LABEL_OPS))}.")
            payload = {"operation": operation}
            if operation != "clear":
                payload["id"] = _safe_id(params.get("id"))
            if operation == "add":
                text = params.get("text")
                if not isinstance(text, str) or not text.strip() or len(text) > 160:
                    raise ValueError("text must contain 1-160 characters.")
                payload.update(
                    text=text.strip(),
                    x=_number(params, "x", low=0, high=10000),
                    y=_number(params, "y", low=0, high=10000),
                    color=_color(params),
                )
            command("studio_label", **payload)
            return json.dumps({"status": "done", "action": action, **payload}, ensure_ascii=False)

        if action == "board":
            operation = params.get("operation")
            if operation not in _BOARD_OPS:
                raise ValueError(f"operation must be one of {', '.join(sorted(_BOARD_OPS))}.")
            payload: dict[str, Any] = {"operation": operation}
            if operation == "add":
                shape = params.get("shape")
                if shape not in _BOARD_SHAPES:
                    raise ValueError(f"shape must be one of {', '.join(sorted(_BOARD_SHAPES))}.")
                payload.update(
                    id=_safe_id(params.get("id")),
                    shape=shape,
                    x=_number(params, "x", low=0, high=10000),
                    y=_number(params, "y", low=0, high=10000),
                    color=_color(params),
                )
                if shape in {"line", "arrow", "rect"}:
                    payload.update(
                        x2=_number(params, "x2", low=0, high=10000),
                        y2=_number(params, "y2", low=0, high=10000),
                    )
                if shape == "text":
                    text = params.get("text")
                    if not isinstance(text, str) or not text.strip() or len(text) > 300:
                        raise ValueError("board text must contain 1-300 characters.")
                    payload["text"] = text.strip()
            command("studio_board", **payload)
            return json.dumps({"status": "done", "action": action, **payload}, ensure_ascii=False)

        if action == "camera":
            mode = params.get("mode")
            if mode not in {"zoom", "pan", "reset", "top_view"}:
                raise ValueError("camera mode must be zoom, pan, reset, or top_view.")
            payload = {"mode": mode}
            if mode == "zoom":
                payload["factor"] = _number(params, "factor", low=0.25, high=4)
            elif mode == "pan":
                payload["x"] = _number(params, "x", low=-100, high=100)
                payload["y"] = _number(params, "y", low=-100, high=100)
            command("studio_camera", **payload)
            return json.dumps({"status": "done", "action": action, **payload})

        if action == "html":
            operation = params.get("operation")
            if operation not in _HTML_OPS:
                raise ValueError("HTML operation must be show or close.")
            payload = {"operation": operation}
            if operation == "show":
                title = params.get("title")
                document = params.get("html")
                if not isinstance(title, str) or not title.strip() or len(title) > 120:
                    raise ValueError("title must contain 1-120 characters.")
                if not isinstance(document, str) or not document.strip():
                    raise ValueError("html must not be empty.")
                try:
                    document_size = len(document.encode("utf-8"))
                except UnicodeEncodeError as exc:
                    raise ValueError("html must be valid UTF-8.") from exc
                if document_size > _MAX_HTML_BYTES:
                    raise ValueError(
                        f"html must be at most {_MAX_HTML_BYTES} UTF-8 bytes."
                    )
                payload.update(title=title.strip(), html=document)
            command("studio_html", **payload)
            return json.dumps(
                {"status": "done", "action": action, **{
                    key: value for key, value in payload.items() if key != "html"
                }},
                ensure_ascii=False,
            )

        operation = params.get("operation")
        if operation not in _SCENE_OPS:
            raise ValueError(f"scene operation must be one of {', '.join(sorted(_SCENE_OPS))}.")
        payload = {"operation": operation}
        if operation != "list":
            payload["name"] = _safe_id(params.get("name"), "name")
        command("studio_scene", **payload)
        return json.dumps({"status": "done", "action": action, **payload})
    except ValueError as exc:
        return json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False)


TOOL = {
    "name": "interface_studio",
    "description": (
        "Edits JARVIS's own visual workspace. Use edit_mode to enable movable/resizable "
        "HUD panels, panel to show/hide/reposition/resize a named HUD panel, label to "
        "add/remove/clear safe text annotations, board to create a visual whiteboard "
        "with text/line/arrow/rectangle/clear/show/hide, camera to zoom/pan/reset/top "
        "view the 3D HUD, scene to save/load/delete/list named local HUD layouts, or "
        "html to preview agent-generated HTML in an isolated sandboxed workspace. "
        "Coordinates are CSS pixels. This does not edit arbitrary code, files, or "
        "third-party pages. Preview scripts, network access, forms, and popups are "
        "blocked. UI-only scene presets stay in browser local storage."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": sorted(_ACTIONS)},
            "enabled": {"type": "BOOLEAN", "description": "Required for edit_mode."},
            "panel": {"type": "STRING", "enum": sorted(_PANELS)},
            "visible": {"type": "BOOLEAN"},
            "x": {"type": "NUMBER"},
            "y": {"type": "NUMBER"},
            "width": {"type": "NUMBER"},
            "height": {"type": "NUMBER"},
            "operation": {"type": "STRING"},
            "id": {"type": "STRING"},
            "name": {"type": "STRING"},
            "text": {"type": "STRING"},
            "color": {"type": "STRING"},
            "shape": {"type": "STRING", "enum": sorted(_BOARD_SHAPES)},
            "x2": {"type": "NUMBER"},
            "y2": {"type": "NUMBER"},
            "mode": {"type": "STRING"},
            "factor": {"type": "NUMBER"},
            "html": {
                "type": "STRING",
                "description": "HTML document or fragment to preview (maximum 100,000 UTF-8 bytes).",
            },
            "title": {"type": "STRING", "description": "Preview window title."},
        },
        "required": ["action"],
    },
    "risk_class": "write",
    "handler": interface_studio,
}

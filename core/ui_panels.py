"""Panel visibility state, layout presets and layout persistence for the HUD. No Qt imports."""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path

# header/footer/content live in the central area; the DOCKS are movable, closable and floatable.
DOCKS = ("controls", "activity_log", "input")
PANELS = ("header", "controls", "activity_log", "input", "content", "footer")

# Names the previous layout (and natural speech) used: one name can cover several panels.
ALIASES: dict[str, tuple[str, ...]] = {
    "left": ("controls",),
    "right": ("activity_log", "input"),
    "log": ("activity_log",),
}

WORKSPACES: dict[str, dict[str, bool]] = {
    "full":   {"header": True,  "controls": True,  "activity_log": True,  "input": True,  "content": True, "footer": True},
    "focus":  {"header": True,  "controls": False, "activity_log": False, "input": False, "content": True, "footer": True},
    "coding": {"header": True,  "controls": False, "activity_log": True,  "input": True,  "content": True, "footer": False},
    "recon":  {"header": False, "controls": False, "activity_log": False, "input": False, "content": True, "footer": False},
}

LAYOUT_VERSION = 1


def resolve(panel: str) -> tuple[str, ...]:
    key = str(panel).strip().lower().replace(" ", "_").replace("-", "_")
    if key in PANELS:
        return (key,)
    if key in ALIASES:
        return ALIASES[key]
    names = ", ".join(PANELS + tuple(ALIASES))
    raise ValueError(f"Unknown panel '{panel}'. Use one of: {names}.")


class PanelState:
    def __init__(self) -> None:
        self._visible = dict(WORKSPACES["full"])
        self.workspace = "full"

    def visible(self, panel: str) -> bool:
        return all(self._visible[name] for name in resolve(panel))

    def set_visible(self, panel: str, value: bool) -> None:
        for name in resolve(panel):
            self._visible[name] = bool(value)
        self.workspace = "custom"

    def apply_workspace(self, name: str) -> dict[str, bool]:
        key = str(name).strip().lower()
        if key not in WORKSPACES:
            raise ValueError(
                f"Unknown workspace '{name}'. Use one of: {', '.join(WORKSPACES)}."
            )
        self._visible = dict(WORKSPACES[key])
        self.workspace = key
        return dict(self._visible)

    def restore(self, visible: dict[str, bool], workspace: str) -> None:
        self._visible = {name: bool(visible.get(name, True)) for name in PANELS}
        self.workspace = workspace

    def snapshot(self) -> dict[str, bool]:
        return dict(self._visible)


def layout_anomalies(data: dict) -> list[str]:
    """Why a loaded layout must be ignored. The input dock is never floating by default and
    must stay reachable: a saved layout that says otherwise is a corrupt or stranded one."""
    problems = []
    if (data.get("floating") or {}).get("input"):
        problems.append("input floating")
    return problems


_CHAT_REQUEST = re.compile(
    r"\b(apri|aprimi|mostra|mostrami)\s+(la\s+|il\s+)?chat\b|\bparliamo\b|\bparlami\b"
    r"|\bopen\s+(the\s+)?chat\b|\blet'?s\s+(talk|chat)\b",
    re.IGNORECASE,
)


def wants_chat(text: str) -> bool:
    """True when the user explicitly asks for the chat ('apri la chat', 'parliamo')."""
    return bool(_CHAT_REQUEST.search(str(text or "")))


def layout_path() -> Path:
    override = os.environ.get("JARVIS_UI_LAYOUT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config" / "ui_layout.json"


def save_layout(path: Path, *, qt_state: bytes, panels: dict[str, bool], workspace: str,
                floating: dict[str, bool], geometry: bytes = b"") -> None:
    """Atomic write, so a crash mid-save cannot leave a half-written layout."""
    payload = {
        "version": LAYOUT_VERSION,
        "workspace": workspace,
        "panels": {name: bool(panels.get(name, True)) for name in PANELS},
        "floating": {name: bool(floating.get(name, False)) for name in DOCKS},
        "qt_state": base64.b64encode(qt_state).decode("ascii"),
        "geometry": base64.b64encode(geometry).decode("ascii"),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def load_layout(path: Path) -> dict | None:
    """The saved layout, or None when missing, unreadable or from another version."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != LAYOUT_VERSION:
            return None
        panels = data["panels"]
        floating = data.get("floating") or {}
        if not isinstance(panels, dict) or not isinstance(floating, dict):
            return None
        return {
            "workspace": str(data.get("workspace", "custom")),
            "panels": {name: bool(panels.get(name, True)) for name in PANELS},
            "floating": {name: bool(floating.get(name, False)) for name in DOCKS},
            "qt_state": base64.b64decode(data["qt_state"], validate=True),
            "geometry": base64.b64decode(data.get("geometry") or "", validate=True),
        }
    except (OSError, ValueError, KeyError, TypeError, binascii.Error):
        return None

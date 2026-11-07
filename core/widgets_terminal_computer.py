"""Dedicated Qt widgets for terminal output and guarded computer-use status."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_STYLE = """
    QWidget { background: #010d14; color: #c8e6ff; }
    QLabel { color: #c8e6ff; }
    QPushButton {
        background: #062131; color: #00bfff; border: 1px solid #0d526b;
        border-radius: 4px; padding: 5px 9px;
    }
    QPushButton:hover { background: #0a3549; }
    QTextEdit {
        background: #00060a; color: #c8e6ff; border: 1px solid #0d2233;
        font-family: "Courier New";
    }
"""
_MAX_SCROLLBACK = 32_000


def _action_callback(spec: dict) -> Callable[[str], Any] | None:
    payload = spec.get("payload", {})
    return spec.get("on_action") or payload.get("_on_action") or payload.get("on_action")


def validate_terminal_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise TypeError("terminal widget payload must be a dictionary.")
    return None


class TerminalWidget(QWidget):
    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self._on_action = _action_callback(spec)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        self._scrollback = QTextEdit()
        self._scrollback.setReadOnly(True)
        self._scrollback.setMinimumHeight(120)
        layout.addWidget(self._scrollback, 1)
        self._cwd = QLabel("")
        self._cwd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self._cwd)
        self.update_payload(spec.get("payload", {}))

    def update_payload(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("event") == "clear":
            self._scrollback.clear()
        chunks = []
        if payload.get("command"):
            chunks.append(f"$ {payload['command']}")
        if payload.get("stdout"):
            chunks.append(str(payload["stdout"]))
        if payload.get("stderr"):
            chunks.append(str(payload["stderr"]))
        if payload.get("reason") and payload.get("event") in {
            "blocked", "timeout", "error", "cancelled"
        }:
            chunks.append(str(payload["reason"]))
        if chunks:
            current = self._scrollback.toPlainText()
            combined = "\n".join(part for part in (current, *chunks) if part)
            self._scrollback.setPlainText(combined[-_MAX_SCROLLBACK:])
            self._scrollback.moveCursor(QTextCursor.MoveOperation.End)
        if "cwd" in payload:
            self._cwd.setText(str(payload.get("cwd") or ""))


def register_widget_types(registry) -> dict[str, bool]:
    registry.register("terminal", validate_terminal_spec, TerminalWidget)
    return {"terminal": True}


def build_terminal_spec(on_action: Callable[[str], Any]) -> dict:
    return {"_on_action": on_action, "event": "idle", "stdout": "", "stderr": "", "cwd": ""}

"""
core/widget_renderers.py — QWidget renderers for JARVIS widget system.

Each renderer is a self-contained QWidget that:
 - Accepts a spec dict in __init__
 - Exposes update_payload(payload) for in-place refresh
 - Matches the style of the existing JARVIS HUD (dark theme, C.* colors)

This module also registers renderers into the WidgetRegistry on import.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar,
    QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QListWidget, QListWidgetItem,
)

# ── JARVIS colour constants (mirror of ui.py's C class) ──────────────────────
_BG       = "#00060a"
_PANEL    = "#010d14"
_ACCENT   = "#00bfff"
_TEXT     = "#c8e6ff"
_TEXT_MED = "#5a8aaa"
_BORDER   = "#0d2233"
_WARN     = "#ffaa00"
_ERR      = "#ff4444"
_OK       = "#00e676"

_FONT_MAIN = "Segoe UI"
_FONT_MONO = "Courier New"


def _title_label(text: str) -> QLabel:
    lbl = QLabel(text.upper()[:48])
    lbl.setFont(QFont(_FONT_MAIN, 8, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {_ACCENT}; background: transparent;")
    return lbl


def _frame(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setStyleSheet(f"""
        QFrame {{
            background: {_PANEL};
            border: 1px solid {_BORDER};
            border-radius: 6px;
        }}
    """)
    return f


# ── BASE ─────────────────────────────────────────────────────────────────────
class _BaseRenderer(QWidget):
    """Common base: title bar + content area."""

    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self._spec = spec
        self.setStyleSheet(f"background: {_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        self._title_lbl = _title_label(spec.get("title", ""))
        outer.addWidget(self._title_lbl)

        self._body = _frame()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 6, 8, 6)
        outer.addWidget(self._body)

        self._build_body(spec.get("payload", {}))

    def _build_body(self, payload: dict):
        raise NotImplementedError

    def update_payload(self, payload: dict):
        raise NotImplementedError


# ── TEXT ─────────────────────────────────────────────────────────────────────
class TextRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        from PyQt6.QtWidgets import QPlainTextEdit
        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setFont(QFont(_FONT_MONO, 9))
        self._edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {_PANEL};
                color: {_TEXT};
                border: none;
                selection-background-color: {_ACCENT};
            }}
        """)
        self._edit.setPlainText(payload.get("text", ""))
        self._body_layout.addWidget(self._edit)

    def update_payload(self, payload: dict):
        self._edit.setPlainText(payload.get("text", ""))


# ── PROGRESS ─────────────────────────────────────────────────────────────────
class ProgressRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(int(payload.get("value", 0)))
        self._bar.setTextVisible(True)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_BG};
                border: 1px solid {_BORDER};
                border-radius: 4px;
                color: {_TEXT};
                text-align: center;
                height: 18px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {_ACCENT}, stop:1 #0077aa);
                border-radius: 3px;
            }}
        """)
        self._phase_lbl = QLabel(payload.get("phase", ""))
        self._phase_lbl.setFont(QFont(_FONT_MAIN, 8))
        self._phase_lbl.setStyleSheet(f"color: {_TEXT_MED}; background: transparent;")
        self._body_layout.addWidget(self._bar)
        self._body_layout.addWidget(self._phase_lbl)

    def update_payload(self, payload: dict):
        self._bar.setValue(int(payload.get("value", 0)))
        self._phase_lbl.setText(payload.get("phase", ""))


# ── IMAGE ─────────────────────────────────────────────────────────────────────
class ImageRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet(f"background: {_BG};")
        self._img_lbl.setMaximumSize(600, 400)
        self._img_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._caption = QLabel("")
        self._caption.setFont(QFont(_FONT_MAIN, 8))
        self._caption.setStyleSheet(f"color: {_TEXT_MED}; background: transparent;")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._body_layout.addWidget(self._img_lbl)
        self._body_layout.addWidget(self._caption)
        self._load(payload)

    def _load(self, payload: dict):
        px = QPixmap()
        if "data" in payload:
            px.loadFromData(payload["data"])
        elif "path" in payload:
            px.load(payload["path"])
        if not px.isNull():
            px = px.scaled(580, 380, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            self._img_lbl.setPixmap(px)
        else:
            self._img_lbl.setText("⚠ Image could not be loaded")
        self._caption.setText(payload.get("caption", ""))

    def update_payload(self, payload: dict):
        self._load(payload)


# ── TABLE ─────────────────────────────────────────────────────────────────────
class TableRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        headers = payload.get("headers", [])
        rows    = payload.get("rows", [])
        self._table = QTableWidget(len(rows), len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {_BG}; color: {_TEXT};
                gridline-color: {_BORDER}; border: none;
            }}
            QHeaderView::section {{
                background: {_PANEL}; color: {_ACCENT};
                border: 1px solid {_BORDER}; font-size: 9px;
            }}
        """)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setVisible(False)
        self._fill(rows)
        self._body_layout.addWidget(self._table)

    def _fill(self, rows: list):
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                item = QTableWidgetItem(str(cell))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)

    def update_payload(self, payload: dict):
        self._fill(payload.get("rows", []))


# ── LIST ─────────────────────────────────────────────────────────────────────
class ListRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background: {_BG}; color: {_TEXT};
                border: none; font-size: 11px;
            }}
            QListWidget::item:selected {{ background: {_ACCENT}; color: {_BG}; }}
            QListWidget::item {{ padding: 3px 6px; }}
        """)
        self._fill(payload.get("items", []))
        self._body_layout.addWidget(self._list)

    def _fill(self, items: list):
        self._list.clear()
        for item in items:
            if isinstance(item, dict):
                icon = item.get("icon", "•")
                label = item.get("label", str(item))
                self._list.addItem(f"{icon}  {label}")
            else:
                self._list.addItem(str(item))

    def update_payload(self, payload: dict):
        self._fill(payload.get("items", []))


# ── TOAST ─────────────────────────────────────────────────────────────────────
_KIND_COLORS = {
    "info":    _ACCENT,
    "success": _OK,
    "warning": _WARN,
    "error":   _ERR,
}


class ToastRenderer(QWidget):
    """
    Compact notification bar — not a full _BaseRenderer.
    Appears at the bottom of the overlay area and fades out when TTL expires.
    """
    def __init__(self, spec: dict, parent=None):
        super().__init__(parent)
        self._spec = spec
        payload = spec.get("payload", {})
        kind    = payload.get("kind", "info")
        color   = _KIND_COLORS.get(kind, _ACCENT)

        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            background: {_PANEL};
            border-left: 4px solid {color};
            border-radius: 4px;
        """)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)

        icon_map = {"info": "ℹ", "success": "✔", "warning": "⚠", "error": "✖"}
        icon_lbl = QLabel(icon_map.get(kind, "ℹ"))
        icon_lbl.setStyleSheet(f"color: {color}; font-size: 14px; background: transparent;")
        lay.addWidget(icon_lbl)

        msg_lbl = QLabel(payload.get("message", "")[:200])
        msg_lbl.setFont(QFont(_FONT_MAIN, 9))
        msg_lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
        lay.addWidget(msg_lbl, 1)

    def update_payload(self, payload: dict):
        pass   # Toasts are not updated in-place


# ── GAUGE ─────────────────────────────────────────────────────────────────────
class GaugeRenderer(_BaseRenderer):
    """Simple textual gauge — arc-style requires Qt drawing; use progress bar style."""
    def _build_body(self, payload: dict):
        v   = float(payload.get("value", 0))
        lo  = float(payload.get("min_val", 0))
        hi  = float(payload.get("max_val", 100))
        pct = int(((v - lo) / max(hi - lo, 1)) * 100)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(pct)
        self._bar.setFormat(f"{v} / {hi}")
        self._bar.setTextVisible(True)
        self._bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_BG}; border: 1px solid {_BORDER};
                border-radius: 4px; color: {_TEXT}; text-align: center;
            }}
            QProgressBar::chunk {{
                background: {'#ff4444' if pct >= 80 else _ACCENT};
                border-radius: 3px;
            }}
        """)
        self._v = v
        self._lo = lo
        self._hi = hi
        self._body_layout.addWidget(self._bar)

    def update_payload(self, payload: dict):
        v  = float(payload.get("value", self._v))
        lo = float(payload.get("min_val", self._lo))
        hi = float(payload.get("max_val", self._hi))
        pct = int(((v - lo) / max(hi - lo, 1)) * 100)
        self._bar.setValue(pct)
        self._bar.setFormat(f"{v} / {hi}")


# ── TOGGLE LIST ───────────────────────────────────────────────────────────────
class ToggleListRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        self._rows: list[tuple[QLabel, QLabel]] = []
        for item in payload.get("items", []):
            row_w = QWidget()
            row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 2, 0, 2)
            lbl = QLabel(item.get("label", ""))
            lbl.setFont(QFont(_FONT_MAIN, 10))
            lbl.setStyleSheet(f"color: {_TEXT}; background: transparent;")
            state_lbl = QLabel("ON" if item.get("state") else "OFF")
            state_lbl.setFont(QFont(_FONT_MAIN, 9, QFont.Weight.Bold))
            c = _OK if item.get("state") else _ERR
            state_lbl.setStyleSheet(f"color: {c}; background: transparent;")
            row_l.addWidget(lbl, 1)
            row_l.addWidget(state_lbl)
            self._body_layout.addWidget(row_w)
            self._rows.append((lbl, state_lbl))

    def update_payload(self, payload: dict):
        items = payload.get("items", [])
        for i, item in enumerate(items):
            if i < len(self._rows):
                lbl, state_lbl = self._rows[i]
                lbl.setText(item.get("label", ""))
                on = item.get("state", False)
                state_lbl.setText("ON" if on else "OFF")
                c = _OK if on else _ERR
                state_lbl.setStyleSheet(f"color: {c}; background: transparent;")


# ── COUNTDOWN ─────────────────────────────────────────────────────────────────
class CountdownRenderer(_BaseRenderer):
    def _build_body(self, payload: dict):
        self._secs = int(payload.get("seconds", 0))
        self._lbl = QLabel(self._fmt(self._secs))
        self._lbl.setFont(QFont(_FONT_MONO, 28, QFont.Weight.Bold))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setStyleSheet(f"color: {_ACCENT}; background: transparent;")
        self._phase_lbl = QLabel(payload.get("phase", ""))
        self._phase_lbl.setFont(QFont(_FONT_MAIN, 9))
        self._phase_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase_lbl.setStyleSheet(f"color: {_TEXT_MED}; background: transparent;")
        self._body_layout.addWidget(self._lbl)
        self._body_layout.addWidget(self._phase_lbl)

    @staticmethod
    def _fmt(s: int) -> str:
        m, sec = divmod(max(s, 0), 60)
        return f"{m:02d}:{sec:02d}"

    def update_payload(self, payload: dict):
        self._secs = int(payload.get("seconds", self._secs))
        self._lbl.setText(self._fmt(self._secs))
        if "phase" in payload:
            self._phase_lbl.setText(payload["phase"])


# ── Register renderers into WidgetRegistry ────────────────────────────────────
def _register_all():
    from core.widget_registry import registry
    registry.set_renderer("text",        TextRenderer)
    registry.set_renderer("progress",    ProgressRenderer)
    registry.set_renderer("image",       ImageRenderer)
    registry.set_renderer("table",       TableRenderer)
    registry.set_renderer("list",        ListRenderer)
    registry.set_renderer("toast",       ToastRenderer)
    registry.set_renderer("gauge",       GaugeRenderer)
    registry.set_renderer("toggle_list", ToggleListRenderer)
    registry.set_renderer("countdown",   CountdownRenderer)


_register_all()

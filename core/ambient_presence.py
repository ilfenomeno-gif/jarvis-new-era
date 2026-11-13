"""Local presence classification and user-selected interruption policy."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

FOCUS = "FOCUS"
AVAILABLE = "AVAILABLE"
AWAY = "AWAY"


class AmbientPresence:
    def __init__(self, context, *, clock: Callable[[], float] = time.monotonic):
        self._context = context
        self._clock = clock
        self._lock = threading.RLock()
        self._category = None
        self._category_since = clock()
        self._forced_focus = False
        self._silent_until = 0.0
        if context is not None and hasattr(context, "add_window_listener"):
            context.add_window_listener(self._context_changed)
            self._context_changed()

    def _context_changed(self) -> None:
        self.get_presence_state(self._context.get_context())

    def set_mode(self, mode: str) -> None:
        with self._lock:
            if mode == "focus":
                self._forced_focus = True
                self._silent_until = 0.0
            elif mode == "normal":
                self._forced_focus = False
                self._silent_until = 0.0
            elif mode == "silent":
                self._forced_focus = False
                self._silent_until = self._clock() + 3600
            else:
                raise ValueError(f"Modalità ambientale non valida: {mode}")

    def is_silent(self) -> bool:
        with self._lock:
            return self._clock() < self._silent_until

    def is_away(self, context: dict | None = None) -> bool:
        if context is None:
            context = self._context.get_context() if self._context is not None else {}
        idle = context.get("idle_minutes")
        return context.get("locked") is True or (
            isinstance(idle, (int, float)) and not isinstance(idle, bool) and idle > 15
        )

    def get_presence_state(self, context: dict | None = None) -> str:
        if context is None:
            context = self._context.get_context() if self._context is not None else {}
        with self._lock:
            now = self._clock()
            category = context.get("window_category")
            if category != self._category:
                self._category = category
                self._category_since = now
            if self._forced_focus:
                return FOCUS
            idle = context.get("idle_minutes")
            idle = idle if isinstance(idle, (int, float)) and not isinstance(idle, bool) and idle >= 0 else None
            if self.is_away(context):
                return AWAY
            if context.get("locked") is not False:
                return FOCUS
            if category in {"editor di codice", "ufficio", "call"} and now - self._category_since > 300:
                return FOCUS
            if category in {"editor di codice", "ufficio", "call"}:
                return AVAILABLE
            if category == "relax" or (idle is not None and 2 <= idle <= 10):
                return AVAILABLE
            return FOCUS

    def channel(self, confidence: float, context: dict | None = None) -> tuple[str, str]:
        if context is None:
            context = self._context.get_context() if self._context is not None else {}
        state = self.get_presence_state(context)
        if state == AWAY or self.is_away(context):
            return state, "SKIP"
        if state == FOCUS or self.is_silent() or confidence <= 0.9:
            return state, "UI_ONLY"
        return state, "VOICE"


def parse_ambient_command(text: str) -> str | None:
    value = re.sub(r"[^\w\sàèéìòù]", " ", text.casefold())
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"^(?:jarvis|iris)\s+", "", value)
    modes = {"modalità focus": "focus", "modalita focus": "focus",
             "modalità normale": "normal", "modalita normale": "normal",
             "modalità silenziosa": "silent", "modalita silenziosa": "silent"}
    return modes.get(value)

"""Small thread-safe bridge from actions to the live UI and widget handlers."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

_lock = threading.RLock()
_condition = threading.Condition(_lock)
_ui: Any = None
_handlers: dict[tuple[str, str], Callable[[], Any]] = {}
_pending_events: deque[tuple[str, dict]] = deque(maxlen=256)
_terminal_cwd: str | None = None
_paused = False
_stopped = False


def set_ui(ui: Any) -> None:
    """Attach the UI and replay events emitted during startup."""
    global _ui
    if ui is None or not callable(getattr(ui, "update_widget", None)):
        raise TypeError("ui must provide update_widget(id, payload).")
    with _lock:
        _ui = ui
        while _pending_events:
            widget_id, payload = _pending_events.popleft()
            _ui.update_widget(widget_id, payload)


def get_ui() -> Any:
    with _lock:
        return _ui


def push_event(widget_id: str, payload: dict) -> None:
    global _terminal_cwd
    if not isinstance(widget_id, str) or not widget_id:
        raise ValueError("widget_id must be non-empty text.")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dictionary.")
    with _lock:
        if widget_id == "terminal" and isinstance(payload.get("cwd"), str):
            _terminal_cwd = payload["cwd"]
        if _ui is None:
            _pending_events.append((widget_id, dict(payload)))
            return
        _ui.update_widget(widget_id, dict(payload))


def get_terminal_widget() -> str:
    return "terminal"


def get_terminal_cwd() -> str | None:
    with _lock:
        return _terminal_cwd


def get_computer_widget() -> str:
    return "computer_use"


def register_handler(widget_id: str, action: str, fn: Callable[[], Any]) -> None:
    if not isinstance(widget_id, str) or not widget_id:
        raise ValueError("widget_id must be non-empty text.")
    if not isinstance(action, str) or not action:
        raise ValueError("action must be non-empty text.")
    if not callable(fn):
        raise TypeError("fn must be callable.")
    with _lock:
        _handlers[(widget_id, action)] = fn


def dispatch(widget_id: str, action: str) -> Any:
    with _lock:
        handler = _handlers.get((widget_id, action))
    if handler is None:
        raise KeyError(f"No action handler registered for {widget_id}.{action}.")
    return handler()


def set_paused(paused: bool) -> None:
    global _paused
    if not isinstance(paused, bool):
        raise TypeError("paused must be a boolean.")
    with _condition:
        _paused = paused
        _condition.notify_all()


def toggle_paused() -> bool:
    global _paused
    with _condition:
        _paused = not _paused
        _condition.notify_all()
        return _paused


def is_paused() -> bool:
    with _lock:
        return _paused


def stop() -> None:
    global _stopped, _paused
    with _condition:
        _stopped = True
        _paused = False
        _condition.notify_all()


def wait_if_paused() -> None:
    with _condition:
        while _paused and not _stopped:
            _condition.wait()
        if _stopped:
            raise InterruptedError("Computer Use was stopped.")


def clear() -> None:
    global _ui, _paused, _stopped, _terminal_cwd
    with _condition:
        _ui = None
        _handlers.clear()
        _pending_events.clear()
        _terminal_cwd = None
        _paused = False
        _stopped = False
        _condition.notify_all()

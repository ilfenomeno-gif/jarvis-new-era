from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable

Subscriber = Callable[[dict], None]
_LOGGER = logging.getLogger(__name__)
_ALLOWED_FIELDS = {
    "trace_id",
    "model",
    "provider",
    "tokens",
    "input_tokens",
    "output_tokens",
    "ms",
    "ok",
    "error_code",
    "role",
    "module",
    "tool",
    "agent",
    "session",
}
_LOCK = threading.RLock()
_SUBSCRIBERS: dict[str, list[Subscriber]] = {}
_BUFFER: deque[tuple[str, dict]] = deque(maxlen=256)


def _safe_payload(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key in _ALLOWED_FIELDS}


def subscribe(topic: str, fn: Subscriber) -> None:
    with _LOCK:
        subscribers = _SUBSCRIBERS.setdefault(topic, [])
        if fn not in subscribers:
            subscribers.append(fn)
        replay = [(name, data) for name, data in _BUFFER if name == topic]
        if replay:
            retained = [(name, data) for name, data in _BUFFER if name != topic]
            _BUFFER.clear()
            _BUFFER.extend(retained)
    for _, payload in replay:
        try:
            fn(dict(payload))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("LLM event subscriber failed for %s: %s", topic, exc)
            continue


def unsubscribe(topic: str, fn: Subscriber) -> None:
    with _LOCK:
        subscribers = _SUBSCRIBERS.get(topic, [])
        if fn in subscribers:
            subscribers.remove(fn)
        if not subscribers:
            _SUBSCRIBERS.pop(topic, None)


def publish(topic: str, payload: dict) -> None:
    safe_payload = _safe_payload(payload)
    with _LOCK:
        subscribers = tuple(_SUBSCRIBERS.get(topic, ()))
        if not subscribers:
            _BUFFER.append((topic, safe_payload))
    for fn in subscribers:
        try:
            fn(dict(safe_payload))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("LLM event subscriber failed for %s: %s", topic, exc)
            continue


def buffer_size() -> int:
    with _LOCK:
        return len(_BUFFER)


def drain_buffer(fn: Callable[[str, dict], None]) -> int:
    with _LOCK:
        pending = list(_BUFFER)
        _BUFFER.clear()
    for topic, payload in pending:
        try:
            fn(topic, dict(payload))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("LLM event buffer consumer failed for %s: %s", topic, exc)
            continue
    return len(pending)

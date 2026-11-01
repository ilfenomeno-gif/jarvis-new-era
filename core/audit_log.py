"""Append-only JSONL audit trail for connector and tool calls."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_SENSITIVE_MARKERS = ("token", "secret", "password", "authorization", "api_key", "apikey")


def _redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if any(m in str(k).lower() for m in _SENSITIVE_MARKERS) else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


class AuditLog:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record(self, *, tool: str, outcome: str, skill: str | None = None,
               scope: str | None = None, connector: str | None = None,
               arguments: dict | None = None, detail: str = "") -> dict:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tool": tool,
            "connector": connector,
            "skill": skill,
            "scope": scope,
            "outcome": outcome,
            "arguments": _redact(arguments or {}),
            "detail": detail,
        }
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self._path.exists():
            return []
        out = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SAFE_FIELDS = {
    "trace_id",
    "span_id",
    "parent_span_id",
    "run_id",
    "agent",
    "tool",
    "event",
    "outcome",
    "tokens",
    "input_tokens",
    "output_tokens",
    "ms",
    "ok",
    "error_code",
    "status",
    "session_id",
}


class Tracer:
    def __init__(self, journal_path: str | Path = "config/harness_runs.jsonl") -> None:
        self.journal_path = Path(journal_path)
        self._lock = threading.Lock()
        self.trace_id = ""
        self.run_id = ""
        self._started_at = 0.0
        self._span_stack: list[str] = []

    def _append(self, event: str, **metadata: Any) -> dict[str, Any]:
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            **{
                key: value
                for key, value in metadata.items()
                if key in _SAFE_FIELDS and key != "event"
            },
        }
        with self._lock:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record

    def start_run(self, *, agent: str = "", session_id: str = "") -> str:
        self.trace_id = uuid.uuid4().hex
        self.run_id = uuid.uuid4().hex
        self._started_at = time.perf_counter()
        self._span_stack.clear()
        self._append(
            "run_start",
            trace_id=self.trace_id,
            run_id=self.run_id,
            agent=agent,
            session_id=session_id,
        )
        return self.trace_id

    def start_span(self, name: str, *, tool: str = "") -> str:
        span_id = uuid.uuid4().hex
        self._append(
            "span_start",
            trace_id=self.trace_id,
            run_id=self.run_id,
            span_id=span_id,
            parent_span_id=self._span_stack[-1] if self._span_stack else "",
            tool=tool or name,
        )
        self._span_stack.append(span_id)
        return span_id

    def span(self, name: str, *, tool: str = "") -> str:
        return self.start_span(name, tool=tool)

    def end_span(
        self,
        span_id: str,
        *,
        ok: bool,
        tool: str = "",
        error_code: str = "",
        ms: float | None = None,
    ) -> None:
        self._append(
            "span_end",
            trace_id=self.trace_id,
            run_id=self.run_id,
            span_id=span_id,
            tool=tool,
            ok=ok,
            error_code=error_code,
            ms=ms,
        )
        if span_id in self._span_stack:
            self._span_stack.remove(span_id)

    def event(self, name: str, **metadata: Any) -> dict[str, Any]:
        return self._append(
            name,
            trace_id=self.trace_id,
            run_id=self.run_id,
            span_id=self._span_stack[-1] if self._span_stack else "",
            **metadata,
        )

    def end_run(
        self,
        *,
        ok: bool,
        tokens: int | None = None,
        ms: float | None = None,
        error_code: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        elapsed = ms if ms is not None else (
            (time.perf_counter() - self._started_at) * 1000 if self._started_at else None
        )
        return self._append(
            "run_end",
            trace_id=self.trace_id,
            run_id=self.run_id,
            ok=ok,
            tokens=tokens,
            ms=elapsed,
            error_code=error_code,
            status=status,
        )

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.harness.session import HarnessSession

_USAGE_FIELDS = {"input_tokens", "output_tokens", "total_tokens", "cost", "ms"}
_ARTIFACT_FIELDS = {"id", "type", "status", "sha256", "size"}
_HISTORY_ROLES = {"system", "user", "assistant", "tool", "metadata"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
)


class HarnessRecovery:
    def __init__(self, journal_path: str | Path = "config/harness_runs.jsonl") -> None:
        self.journal_path = Path(journal_path)
        self._lock = threading.Lock()

    def checkpoint(self, session: HarnessSession, *, replay_consent: bool = False) -> str:
        history = []
        for item in session.history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            history.append({
                "role": role if isinstance(role, str) and role in _HISTORY_ROLES else "metadata",
                "content_sha256": _digest(content) if isinstance(content, str) else "",
                "content_length": len(content) if isinstance(content, str) else 0,
            })
        record = {
            "event": "checkpoint",
            "ts": datetime.now(UTC).isoformat(),
            "session_id": _safe_label(session.id, digest=True),
            "trace_id": _safe_label(session.trace_id, digest=True),
            "agent": _safe_label(session.agent),
            "goal_sha256": _digest(session.goal),
            "status": _safe_label(session.status),
            "history": history,
            "artifacts": [_safe_artifact(item) for item in session.artifacts
                          if isinstance(item, dict)],
            "usage": {
                key: value
                for key, value in session.usage.items()
                if key in _USAGE_FIELDS and _safe_scalar(value)
            },
            "created_at": _safe_timestamp(session.created_at),
        }
        replay_enabled = os.environ.get("JARVIS_HARNESS_REPLAY") == "1"
        if replay_enabled and replay_consent:
            replay_history = []
            for item in session.history:
                if not isinstance(item, dict):
                    continue
                role = item.get("role")
                content = item.get("content")
                if role in _HISTORY_ROLES and isinstance(content, str):
                    replay_history.append({"role": role, "content": _redact(content)})
            record["replay"] = {
                "goal": session.goal,
                "history": replay_history,
            }
        record["integrity_sha256"] = _record_digest(record)
        with self._lock:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with self.journal_path.open("a", encoding="utf-8") as journal:
                journal.write(json.dumps(record, ensure_ascii=False) + "\n")
        return session.id

    def restore(self, session_id: str, *, replay_consent: bool = False) -> HarnessSession:
        if not self.journal_path.is_file():
            raise FileNotFoundError(f"No harness checkpoint journal at {self.journal_path}.")
        safe_session_id = _safe_label(session_id, digest=True)
        latest = None
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if (
                record.get("event") == "checkpoint"
                and record.get("session_id") == safe_session_id
            ):
                latest = record
        if latest is None:
            raise KeyError(f"No checkpoint exists for harness session {session_id!r}.")
        valid_integrity = latest.get("integrity_sha256") == _record_digest(
            {key: value for key, value in latest.items() if key != "integrity_sha256"}
        )
        replay = latest.get("replay")
        may_replay = (
            os.environ.get("JARVIS_HARNESS_REPLAY") == "1"
            and replay_consent
            and latest.get("integrity_sha256") is not None
            and valid_integrity
            and isinstance(replay, dict)
            and isinstance(replay.get("goal"), str)
            and isinstance(replay.get("history"), list)
        )
        if may_replay:
            history = replay["history"]
            if not all(
                isinstance(item, dict)
                and item.get("role") in _HISTORY_ROLES
                and isinstance(item.get("content"), str)
                for item in history
            ):
                may_replay = False
        session = HarnessSession(
            id=latest["session_id"],
            trace_id=latest["trace_id"],
            agent=latest["agent"],
            goal=replay["goal"] if may_replay else "",
            history=list(replay["history"]) if may_replay else [],
            artifacts=list(latest.get("artifacts", [])),
            usage=dict(latest.get("usage", {})),
            created_at=latest["created_at"],
            status="recovered_replay_ready" if may_replay else "recovered_metadata_only",
            recovery_reason=(
                ""
                if may_replay
                else "Replay requires JARVIS_HARNESS_REPLAY=1, explicit consent, "
                "and a valid integrity hash; checkpoint restored as metadata only."
            ),
        )
        return session


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _record_digest(record: dict[str, Any]) -> str:
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _digest(canonical)


def _redact(content: str) -> str:
    redacted = content
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(
            lambda match: (
                f"{match.group(1)}=[REDACTED]"
                if match.lastindex
                else "Bearer [REDACTED]"
            ),
            redacted,
        )
    return redacted


def _safe_scalar(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _safe_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in _ARTIFACT_FIELDS:
        value = artifact.get(key)
        if key in {"id", "type", "status"} and isinstance(value, str):
            safe_value = _safe_label(value, digest=key == "id")
            if safe_value:
                safe[key] = safe_value
        elif (
            key == "sha256"
            and isinstance(value, str)
            and re.fullmatch(r"[a-fA-F0-9]{64}", value)
        ) or (
            key == "size"
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        ):
            safe[key] = value
    return safe


def _safe_label(value: str, *, digest: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", value):
        return value
    return _digest(value) if digest and value else ""


def _safe_timestamp(value: str) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return datetime.fromisoformat(value).isoformat()
    except ValueError:
        return ""

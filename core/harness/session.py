from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class HarnessSession:
    agent: str
    goal: str
    id: str = field(default_factory=_new_id)
    trace_id: str = field(default_factory=_new_id)
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    status: str = "created"
    recovery_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trace_id": self.trace_id,
            "agent": self.agent,
            "goal": self.goal,
            "history": list(self.history),
            "artifacts": list(self.artifacts),
            "usage": dict(self.usage),
            "created_at": self.created_at,
            "status": self.status,
            "recovery_reason": self.recovery_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HarnessSession:
        if not isinstance(data, dict):
            raise TypeError("HarnessSession data must be a dictionary.")
        return cls(
            id=data.get("id") or _new_id(),
            trace_id=data.get("trace_id") or _new_id(),
            agent=str(data.get("agent", "")),
            goal=str(data.get("goal", "")),
            history=list(data.get("history") or []),
            artifacts=list(data.get("artifacts") or []),
            usage=dict(data.get("usage") or {}),
            created_at=str(data.get("created_at") or _now()),
            status=str(data.get("status", "created")),
            recovery_reason=str(data.get("recovery_reason", "")),
        )

from __future__ import annotations

import json
import os
import threading
from collections import defaultdict
from datetime import date
from pathlib import Path

from core.llm_context import get_context

_LOCK = threading.RLock()
_LIMITS = {
    "max_tokens_session": 0,
    "max_cost_day": 0.0,
    "warn_ratio": 0.8,
}
_SESSIONS: dict[str, dict] = defaultdict(
    lambda: {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
)
_DAILY_COST: dict[str, float] = defaultdict(float)
_PERSIST_PATH = Path(os.environ["JARVIS_LLM_BUDGET_PATH"]) \
    if os.getenv("JARVIS_LLM_BUDGET_PATH") else None


def _load() -> None:
    if _PERSIST_PATH is None or not _PERSIST_PATH.exists():
        return
    try:
        saved = json.loads(_PERSIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not load LLM budget data: {exc}") from exc
    for session, value in saved.get("sessions", {}).items():
        if isinstance(value, dict):
            _SESSIONS[session] = value
    _DAILY_COST.update(saved.get("daily_cost", {}))


def _persist() -> None:
    if _PERSIST_PATH is None:
        return
    _PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _PERSIST_PATH.with_suffix(_PERSIST_PATH.suffix + ".tmp")
    data = {"sessions": dict(_SESSIONS), "daily_cost": dict(_DAILY_COST)}
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        temporary.replace(_PERSIST_PATH)
    except OSError as exc:
        raise RuntimeError(f"Could not persist LLM budget data: {exc}") from exc


_load()


def set_limits(
    max_tokens_session: int = 0,
    max_cost_day: float = 0,
    warn_ratio: float = 0.8,
) -> None:
    if max_tokens_session < 0 or max_cost_day < 0 or not 0 <= warn_ratio <= 1:
        raise ValueError("Budget limits must be non-negative and warn_ratio in [0, 1].")
    with _LOCK:
        _LIMITS.update(
            max_tokens_session=max_tokens_session,
            max_cost_day=max_cost_day,
            warn_ratio=warn_ratio,
        )


def track_usage(
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cost_estimate: float | None = None,
) -> None:
    if min(input_tokens, output_tokens) < 0:
        raise ValueError("Token usage cannot be negative.")
    context = get_context()
    session = context.get("session", "default")
    cost = max(0.0, cost_estimate or 0.0)
    with _LOCK:
        record = _SESSIONS[session]
        record["input_tokens"] += input_tokens
        record["output_tokens"] += output_tokens
        record["cost"] += cost
        record.setdefault("models", {})[model] = provider
        _DAILY_COST[date.today().isoformat()] += cost
        _persist()


def get_usage(session_id: str | None = None) -> dict:
    with _LOCK:
        if session_id is not None:
            value = dict(_SESSIONS.get(session_id, {}))
            return value or {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
        return {
            "sessions": {key: dict(value) for key, value in _SESSIONS.items()},
            "daily_cost": dict(_DAILY_COST),
        }


def check_budget(session_id: str | None = None) -> str:
    session = session_id or get_context().get("session", "default")
    with _LOCK:
        usage = _SESSIONS.get(session, {})
        tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        max_tokens = _LIMITS["max_tokens_session"]
        cost = _DAILY_COST.get(date.today().isoformat(), 0.0)
        max_cost = _LIMITS["max_cost_day"]
        ratios = []
        if max_tokens:
            ratios.append(tokens / max_tokens)
        if max_cost:
            ratios.append(cost / max_cost)
        if any(ratio >= 1 for ratio in ratios):
            return "exceeded"
        if any(ratio >= _LIMITS["warn_ratio"] for ratio in ratios):
            return "warning"
        return "ok"

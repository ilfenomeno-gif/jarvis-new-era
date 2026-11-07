"""SQLite-backed task queue with restart recovery and a polling worker."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from core.internal_workflow import default_database_path

TaskStatus = Literal["pending", "running", "done", "failed"]
TaskHandler = Callable[[str], Any]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _acknowledge_task(_task: str) -> dict[str, str]:
    return {
        "status": "accepted",
        "detail": "Queue worker consumed the task; no Jarvis execution handler is configured.",
    }


@dataclass(frozen=True)
class QueuedTask:
    task_id: str
    task: str
    status: TaskStatus
    created_at: str
    updated_at: str
    result: Any = None
    error: str = ""


class TaskQueue:
    """Durable task storage; worker delivery is at-least-once across crashes."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        handler: TaskHandler | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.handler = handler or _acknowledge_task
        self.logger = logger or logging.getLogger(__name__)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS server_tasks (
                    task_id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN ('pending', 'running', 'done', 'failed')
                    ),
                    result_json TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            # A process restart may interrupt a claimed task. Requeue it for at-least-once delivery.
            connection.execute(
                """
                UPDATE server_tasks
                SET status = 'pending', updated_at = ?
                WHERE status = 'running'
                """,
                (_now(),),
            )

    def enqueue(self, task: str) -> QueuedTask:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be non-empty text.")
        normalized = task.strip()
        if len(normalized) > 20_000:
            raise ValueError("task must not exceed 20,000 characters.")
        now = _now()
        item = QueuedTask(uuid.uuid4().hex, normalized, "pending", now, now)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO server_tasks (task_id, task, status, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?)
                """,
                (item.task_id, item.task, now, now),
            )
        return item

    def get(self, task_id: str) -> QueuedTask | None:
        if not isinstance(task_id, str) or not task_id.strip():
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM server_tasks WHERE task_id = ?",
                (task_id.strip(),),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> QueuedTask:
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return QueuedTask(
            task_id=row["task_id"],
            task=row["task"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            result=result,
            error=row["error"],
        )

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM server_tasks GROUP BY status"
            ).fetchall()
        counts = {"pending": 0, "running": 0, "done": 0, "failed": 0}
        counts.update({row["status"]: int(row["count"]) for row in rows})
        return counts

    def claim_next(self) -> QueuedTask | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT task_id FROM server_tasks
                WHERE status = 'pending'
                ORDER BY created_at, task_id LIMIT 1
                """
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            now = _now()
            cursor = connection.execute(
                """
                UPDATE server_tasks SET status = 'running', updated_at = ?
                WHERE task_id = ? AND status = 'pending'
                """,
                (now, row["task_id"]),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
        return self.get(row["task_id"])

    def finish(self, task_id: str, result: Any = None) -> bool:
        try:
            serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("Task result must be JSON serializable.") from exc
        if len(serialized.encode("utf-8")) > 100_000:
            raise ValueError("Task result must not exceed 100 KB.")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE server_tasks SET status = 'done', result_json = ?,
                    error = '', updated_at = ?
                WHERE task_id = ? AND status = 'running'
                """,
                (serialized, _now(), task_id),
            )
        return cursor.rowcount == 1

    def fail(self, task_id: str, error: str) -> bool:
        # Store only a bounded generic error label; don't persist tracebacks or secrets.
        safe_error = error.strip()[:500] if isinstance(error, str) else "Task failed."
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE server_tasks SET status = 'failed', error = ?, updated_at = ?
                WHERE task_id = ? AND status = 'running'
                """,
                (safe_error or "Task failed.", _now(), task_id),
            )
        return cursor.rowcount == 1

    def run_once(self) -> bool:
        item = self.claim_next()
        if item is None:
            return False
        try:
            result = self.handler(item.task)
            if not self.finish(item.task_id, result):
                raise RuntimeError("Claimed task state changed before completion.")
        except Exception as exc:
            self.fail(item.task_id, type(exc).__name__)
            self.logger.error(
                "Task %s failed (%s).", item.task_id, type(exc).__name__
            )
        return True

    def worker_loop(
        self,
        stop_event: threading.Event,
        *,
        idle_interval: float = 0.25,
    ) -> None:
        if not 0 < idle_interval <= 10:
            raise ValueError("idle_interval must be greater than 0 and at most 10.")
        while not stop_event.is_set():
            if not self.run_once():
                stop_event.wait(idle_interval)

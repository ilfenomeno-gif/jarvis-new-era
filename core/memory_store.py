"""Private SQLite memory and checkpoints for Jarvis intellectual workflows."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.internal_workflow import default_database_path

MEMORY_SCOPES = frozenset({"session", "project", "long_term"})


class _PooledConnection:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.lock = threading.RLock()
        self.closed = False


def _json_value(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Memory values must be JSON serializable.") from exc


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class MemoryStore:
    """Transactional SQLite storage sharing Jarvis's private application database."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        pool_flag = os.environ.get(
            "JARVIS_MEMORY_POOL", os.environ.get("JARVIS_SQLITE_POOLED", "0")
        )
        self._pooled = pool_flag == "1"
        self._connection_lock = threading.RLock()
        self._thread_connections = threading.local()
        self._pool_connections: dict[int, _PooledConnection] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            check_same_thread=not self._pooled,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self._pooled:
            connection = self._connect()
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
            return

        while True:
            with self._connection_lock:
                entry = getattr(self._thread_connections, "entry", None)
                if entry is None or entry.closed:
                    connection = self._connect()
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA synchronous = NORMAL")
                    entry = _PooledConnection(connection)
                    self._thread_connections.entry = entry
                    self._pool_connections[id(connection)] = entry
            with entry.lock:
                if entry.closed:
                    continue
                with entry.connection:
                    yield entry.connection
                return

    def close(self) -> None:
        """Close all optional per-thread connections; legacy stores have none."""
        if not self._pooled:
            return
        with self._connection_lock:
            entries = tuple(self._pool_connections.values())
            self._pool_connections.clear()
        for entry in entries:
            with entry.lock:
                if not entry.closed:
                    entry.closed = True
                    entry.connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jarvis_memory (
                    scope TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope, memory_key)
                );
                CREATE TABLE IF NOT EXISTS jarvis_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jarvis_records (
                    namespace TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, record_key)
                );
                CREATE TABLE IF NOT EXISTS jarvis_intellectual_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _validate_scope(scope: str) -> str:
        if scope not in MEMORY_SCOPES:
            raise ValueError(f"scope must be one of {sorted(MEMORY_SCOPES)}.")
        return scope

    @staticmethod
    def _validate_key(key: str, label: str = "key") -> str:
        if not isinstance(key, str) or not key.strip() or len(key) > 500:
            raise ValueError(f"{label} must contain 1 to 500 characters.")
        return key.strip()

    def remember(self, scope: str, key: str, value: Any) -> Any:
        scope = self._validate_scope(scope)
        key = self._validate_key(key)
        encoded = _json_value(value)
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("Memory values must not exceed 1 MB.")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_memory (scope, memory_key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, memory_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                WHERE value_json != excluded.value_json
                """,
                (scope, key, encoded, _now()),
            )
        return value

    def recall(self, scope: str, key: str) -> Any | None:
        scope = self._validate_scope(scope)
        key = self._validate_key(key)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT value_json FROM jarvis_memory
                WHERE scope = ? AND memory_key = ?
                """,
                (scope, key),
            ).fetchone()
        return json.loads(row["value_json"]) if row else None

    def checkpoint(self, state: dict[str, Any] | None = None) -> str:
        """Persist an explicit state or a snapshot of all scoped memory."""
        if state is None:
            with self._connection() as connection:
                rows = connection.execute(
                    """
                    SELECT scope, memory_key, value_json FROM jarvis_memory
                    ORDER BY scope, memory_key
                    """
                ).fetchall()
            state = {
                "memory": [
                    {
                        "scope": row["scope"],
                        "key": row["memory_key"],
                        "value": json.loads(row["value_json"]),
                    }
                    for row in rows
                ]
            }
        if not isinstance(state, dict):
            raise ValueError("Checkpoint state must be a JSON object.")
        encoded = _json_value(state)
        checkpoint_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO jarvis_checkpoints (
                    checkpoint_id, state_json, created_at
                ) VALUES (?, ?, ?)
                """,
                (checkpoint_id, encoded, _now()),
            )
        return checkpoint_id

    def resume(self, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        with self._connection() as connection:
            if checkpoint_id is None:
                row = connection.execute(
                    """
                    SELECT state_json FROM jarvis_checkpoints
                    ORDER BY created_at DESC, checkpoint_id DESC LIMIT 1
                    """
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT state_json FROM jarvis_checkpoints WHERE checkpoint_id = ?",
                    (checkpoint_id,),
                ).fetchone()
        return json.loads(row["state_json"]) if row else None

    def save_record(self, namespace: str, key: str, value: Any) -> None:
        namespace = self._validate_key(namespace, "namespace")
        key = self._validate_key(key)
        encoded = _json_value(value)
        if len(encoded.encode("utf-8")) > 2_000_000:
            raise ValueError("Stored records must not exceed 2 MB.")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_records (namespace, record_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, record_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                WHERE payload_json != excluded.payload_json
                """,
                (namespace, key, encoded, _now()),
            )

    def load_record(self, namespace: str, key: str) -> Any | None:
        namespace = self._validate_key(namespace, "namespace")
        key = self._validate_key(key)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM jarvis_records
                WHERE namespace = ? AND record_key = ?
                """,
                (namespace, key),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def record_event(self, event_key: str, event_type: str, payload: Any) -> None:
        event_key = self._validate_key(event_key, "event_key")
        event_type = self._validate_key(event_type, "event_type")
        encoded = _json_value(payload)
        with self._connection() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO jarvis_intellectual_events (
                    event_key, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (event_key, event_type, encoded, _now()),
            )

    def list_events(self, event_prefix: str) -> list[dict[str, Any]]:
        event_prefix = self._validate_key(event_prefix, "event_prefix")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT event_key, event_type, payload_json, created_at
                FROM jarvis_intellectual_events
                WHERE event_key LIKE ? ESCAPE '\\'
                ORDER BY id
                """,
                (event_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
            ).fetchall()
        return [
            {
                "event_key": row["event_key"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

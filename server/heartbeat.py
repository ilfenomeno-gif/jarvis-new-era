"""Persistent server heartbeat with an injectable alert callback."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

AlertCallback = Callable[[dict[str, str]], None]


class HeartbeatService:
    def __init__(
        self,
        database_path: str | Path,
        *,
        interval_seconds: float = 30,
        alert_callback: AlertCallback | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not 0.1 <= interval_seconds <= 3600
        ):
            raise ValueError("interval_seconds must be between 0.1 and 3600.")
        self.database_path = Path(database_path)
        self.interval_seconds = float(interval_seconds)
        self.alert_callback = alert_callback
        self.logger = logger or logging.getLogger(__name__)
        self._last_heartbeat: str | None = None
        self._last_error: str | None = None
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS server_heartbeats (
                    heartbeat_id TEXT PRIMARY KEY,
                    recorded_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT ''
                )
                """
            )

    @property
    def status(self) -> dict[str, str | None]:
        with self._lock:
            return {
                "last_heartbeat": self._last_heartbeat,
                "last_error": self._last_error,
            }

    def record_once(self) -> str:
        recorded_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO server_heartbeats (heartbeat_id, recorded_at, status, detail)
                VALUES (?, ?, 'ok', '')
                """,
                (uuid.uuid4().hex, recorded_at),
            )
        with self._lock:
            self._last_heartbeat = recorded_at
            self._last_error = None
        return recorded_at

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.record_once()
            except Exception as exc:
                safe_error = type(exc).__name__
                with self._lock:
                    self._last_error = safe_error
                self.logger.error("Heartbeat write failed (%s).", safe_error)
                if self.alert_callback is not None:
                    event = {
                        "type": "heartbeat_failure",
                        "error": safe_error,
                        "occurred_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
                    }
                    try:
                        self.alert_callback(event)
                    except Exception as alert_exc:
                        self.logger.error(
                            "Heartbeat alert callback failed (%s).",
                            type(alert_exc).__name__,
                        )
            if stop_event.wait(self.interval_seconds):
                break


class HeartbeatThread:
    def __init__(self, service: HeartbeatService) -> None:
        self.service = service
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self.service.run,
            args=(self.stop_event,),
            name="jarvis-server-heartbeat",
            daemon=True,
        )

    @property
    def running(self) -> bool:
        return self.thread.is_alive()

    def start(self) -> None:
        if not self.thread.is_alive():
            self.stop_event.clear()
            self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        if self.thread.ident is not None:
            self.thread.join(timeout)
        if self.thread.is_alive():
            raise TimeoutError("Heartbeat thread did not stop before timeout.")

"""Thread-safe suppression and reporting of repeated diagnostic messages."""
from __future__ import annotations

import logging
import threading
import time

from core.log_formatter import NOTICE


class LogThrottler:
    _instance = None
    _instance_lock = threading.Lock()
    _ttls = {"WARNING": 30, "WARN": 30, "ERROR": 5, "NOTICE": 60}

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._lock = threading.Lock()
                cls._instance._last = {}
                cls._instance._counts = {}
            return cls._instance

    def should_log(self, key: str, level: str, ttl_seconds: int | None = None) -> bool:
        level = level.upper()
        if level in {"CRITICAL", "INFO", "DEBUG"}:
            return True
        ttl = self._ttls.get(level, 0) if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            entry = (key, level)
            last = self._last.get(entry)
            if last is not None and now - last[0] < ttl:
                count, started = self._counts.get(key, (0, now))
                if now - started > 300 and count < 10:
                    count, started = 0, now
                self._counts[key] = (count + 1, started)
                return False
            self._last[entry] = (now, ttl)
            return True

    def record(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            count, started = self._counts.get(key, (0, now))
            if now - started > 300 and count < 10:
                count, started = 0, now
            self._counts[key] = (count + 1, started)

    def get_count(self, key: str) -> int:
        with self._lock:
            return self._counts.get(key, (0, 0))[0]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {key: count for key, (count, _) in self._counts.items()}

    def flush_summary(self) -> dict[str, int]:
        now = time.monotonic()
        with self._lock:
            ready = {key: value for key, value in self._counts.items() if value[0] >= 10}
            for key in ready:
                del self._counts[key]
            self._counts = {key: value for key, value in self._counts.items()
                            if now - value[1] <= 300}
            self._last = {
                entry: last for entry, last in self._last.items()
                if now - last[0] < last[1]
            }
        logger = logging.getLogger("system.throttler")
        for key, (count, started) in ready.items():
            logger.log(NOTICE, "Ripetuto %d volte in %.1f min: %s", count,
                       (now - started) / 60, key,
                       extra={"throttled_count": count})
        return {key: count for key, (count, _) in ready.items()}

"""Periodic, local-only diagnostic snapshots."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.log_formatter import NOTICE
from core.log_throttler import LogThrottler

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG = logging.getLogger("system.health")


def recent_records(minutes: int, log_dir: Path = LOG_DIR) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    records = []
    for path in [log_dir / "jarvis.session.jsonl", *(
        log_dir / f"jarvis.session.jsonl.{index}" for index in range(1, 4)
    )]:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    item = json.loads(line)
                    timestamp = datetime.fromisoformat(item["timestamp"])
                    if timestamp.tzinfo is None:
                        raise ValueError("timestamp has no timezone")
                except (ValueError, KeyError, TypeError) as exc:
                    _LOG.warning("Riga JSONL non valida in %s:%d: %s", path.name, line_number, exc)
                    continue
                if cutoff <= timestamp <= datetime.now(UTC):
                    records.append(item)
    return records


def module_status() -> dict:
    from core.symbiosis_hub import get_symbiosis_hub

    hub = get_symbiosis_hub(start=False)
    if hub is None:
        return {"available": False, "active": [], "total": None}
    with hub._lock:
        return {"available": True, "active": sorted(hub._modules), "total": len(hub._selected)}


def hardware_status() -> dict:
    import psutil

    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage(os.path.abspath(os.sep)).percent,
    }


class LogReporter(threading.Thread):
    def __init__(self, interval: float | None = None, log_dir: Path = LOG_DIR):
        super().__init__(name="jarvis-log-reporter", daemon=True)
        self.interval = float(os.environ.get("JARVIS_LOG_REPORT_INTERVAL", "300")) if interval is None else interval
        if self.interval <= 0:
            raise ValueError("Report interval must be positive")
        self.log_dir = log_dir
        self._stop_event = threading.Event()

    def get_snapshot(self) -> dict:
        records = recent_records(5, self.log_dir)
        last_minute = datetime.now(UTC) - timedelta(minutes=1)
        return {
            "modules": module_status(),
            "hardware": hardware_status(),
            "errors": sum(item.get("severity") in {"ERROR", "CRITICAL"} for item in records),
            "critical": sum(item.get("severity") == "CRITICAL" for item in records),
            "lines_last_minute": sum(datetime.fromisoformat(item["timestamp"]) >= last_minute for item in records),
        }

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            LogThrottler().flush_summary()
            try:
                snapshot = self.get_snapshot()
                modules, hardware = snapshot["modules"], snapshot["hardware"]
                active = f"{len(modules['active'])}/{modules['total']}" if modules["available"] else "non disponibili"
                _LOG.log(NOTICE, "Snapshot: %s moduli attivi | CPU %s%% | RAM %s%% | %d errori critici | Log: %d righe (ultimo min)",
                         active, hardware["cpu"], hardware["ram"], snapshot["critical"], snapshot["lines_last_minute"])
            except (OSError, ValueError, ImportError) as exc:
                _LOG.exception("Snapshot diagnostico non disponibile: %s", exc)


_reporter_lock = threading.Lock()
_reporter = None


def start_reporter() -> LogReporter:
    global _reporter
    with _reporter_lock:
        if _reporter is None or not _reporter.is_alive():
            _reporter = LogReporter()
            _reporter.start()
        return _reporter

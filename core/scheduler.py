"""Persistent, in-process scheduler for reminders and briefings."""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "scheduled_tasks.json"


class Scheduler:
    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._callback: Callable[[dict], None] | None = None
        self._retry_after: dict[str, datetime] = {}
        self._tasks = self._load()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Il file dei task pianificati deve contenere una lista.")
        for task in data:
            if not isinstance(task, dict) or task.get("kind") not in {"reminder", "weather", "briefing"}:
                raise ValueError("Task pianificato non valido.")
            if not all(isinstance(task.get(key), str) for key in ("id", "message", "next_run", "schedule")):
                raise ValueError("Campi del task pianificato non validi.")
            run_at = datetime.fromisoformat(task["next_run"])
            if run_at.tzinfo is None or task["schedule"] not in {"once", "daily", "interval"}:
                raise ValueError("Orario o frequenza del task non validi.")
            if task["schedule"] == "daily" and (
                isinstance(task.get("hour"), bool)
                or not isinstance(task.get("hour"), int)
                or not 0 <= task["hour"] <= 23
                or isinstance(task.get("minute"), bool)
                or not isinstance(task.get("minute"), int)
                or not 0 <= task["minute"] <= 59
            ):
                raise ValueError("Orario giornaliero del task non valido.")
            if task["schedule"] == "interval" and (
                isinstance(task.get("interval_seconds"), bool)
                or not isinstance(task.get("interval_seconds"), int)
                or task["interval_seconds"] < 60
            ):
                raise ValueError("Intervallo del task non valido.")
        return data

    def _save(self, tasks: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".scheduled-tasks-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(tasks, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def add(self, kind: str, message: str, schedule: str, *,
            delay_minutes: int | None = None, hour: int | None = None,
            minute: int = 0, at: str | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now().astimezone()
        if now.tzinfo is None:
            raise ValueError("Serve un orario con fuso orario.")
        if kind not in {"reminder", "weather", "briefing"} or schedule not in {"once", "daily", "interval"}:
            raise ValueError("Tipo o frequenza non supportati.")
        if not isinstance(message, str) or len(message.strip()) > 500 or (kind == "reminder" and not message.strip()):
            raise ValueError("Il promemoria deve contenere testo valido (massimo 500 caratteri).")
        interval = None
        if schedule == "daily":
            if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23 or isinstance(minute, bool) or not isinstance(minute, int) or not 0 <= minute <= 59:
                raise ValueError("Ora giornaliera non valida.")
            local = now.astimezone()
            next_run = datetime.combine(local.date(), time(hour, minute)).astimezone()
            if next_run <= local:
                next_run = datetime.combine(local.date() + timedelta(days=1), time(hour, minute)).astimezone()
        elif at is not None and schedule == "once":
            next_run = datetime.fromisoformat(at)
            if next_run.tzinfo is None:
                next_run = next_run.astimezone()
            if next_run <= now:
                raise ValueError("L'orario deve essere futuro.")
        else:
            if isinstance(delay_minutes, bool) or not isinstance(delay_minutes, int) or not 1 <= delay_minutes <= 525600:
                raise ValueError("Inserisci un intervallo da 1 a 525600 minuti.")
            next_run = now + timedelta(minutes=delay_minutes)
            if schedule == "interval":
                interval = delay_minutes * 60
        task = {"id": uuid.uuid4().hex, "kind": kind, "message": message.strip(),
                "schedule": schedule, "next_run": next_run.isoformat()}
        if schedule == "daily":
            task.update(hour=hour, minute=minute)
        if interval is not None:
            task["interval_seconds"] = interval
        with self._lock:
            updated = [*self._tasks, task]
            self._save(updated)
            self._tasks = updated
        self._wake.set()
        return dict(task)

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [dict(task) for task in self._tasks]

    def run_due(self, now: datetime | None = None) -> None:
        now = now or datetime.now().astimezone()
        with self._lock:
            due = [dict(task) for task in self._tasks
                   if datetime.fromisoformat(task["next_run"]) <= now
                   and self._retry_after.get(task["id"], now) <= now]
        for task in due:
            try:
                if self._callback is None:
                    raise RuntimeError("Il servizio di consegna non è inizializzato.")
                self._callback(dict(task))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Consegna task pianificato %s fallita", task["id"])
                self._retry_after[task["id"]] = now + timedelta(seconds=30)
                continue
            with self._lock:
                updated = [dict(item) for item in self._tasks if item["id"] != task["id"]]
                if task["schedule"] == "daily":
                    tomorrow = now.astimezone().date() + timedelta(days=1)
                    next_run = datetime.combine(tomorrow, time(task["hour"], task["minute"])).astimezone()
                    updated.append({**task, "next_run": next_run.isoformat()})
                elif task["schedule"] == "interval":
                    updated.append({**task, "next_run": (now + timedelta(seconds=task["interval_seconds"])).isoformat()})
                self._save(updated)
                self._tasks = updated
                self._retry_after.pop(task["id"], None)

    def start(self, callback: Callable[[dict], None]) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Scheduler già avviato.")
        self._callback = callback
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    self.run_due()
                except (OSError, ValueError):
                    import logging
                    logging.getLogger(__name__).exception("Errore scheduler")
                self._wake.wait(1)
                self._wake.clear()

        self._thread = threading.Thread(target=loop, name="jarvis-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=3)


_instance: Scheduler | None = None
_instance_lock = threading.Lock()


def get_scheduler() -> Scheduler:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Scheduler()
        return _instance

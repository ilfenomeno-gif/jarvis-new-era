"""Health monitoring for subprocesses explicitly owned by Jarvis."""

from __future__ import annotations

import threading
from collections.abc import Callable


class ProcessWatchdog:
    def __init__(
        self,
        *,
        interval: float = 5.0,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("Watchdog interval must be positive.")
        self._interval = interval
        self._logger = logger or (lambda _message: None)
        self._checks: dict[str, tuple[Callable[[], bool], Callable[[], None]]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(
        self,
        name: str,
        is_healthy: Callable[[], bool],
        recover: Callable[[], None],
    ) -> None:
        if not name.strip():
            raise ValueError("A watchdog process name is required.")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("Cannot register a process after watchdog start.")
            if name in self._checks:
                raise ValueError(f"Watchdog process {name!r} is already registered.")
            self._checks[name] = (is_healthy, recover)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="jarvis-process-watchdog",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            with self._lock:
                checks = tuple(self._checks.items())
            for name, (is_healthy, recover) in checks:
                if self._stop.is_set():
                    return
                try:
                    healthy = is_healthy()
                except Exception as exc:
                    self._logger(
                        f"[WATCHDOG] Health check failed for {name}: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    continue
                if healthy:
                    continue
                self._logger(
                    f"[WATCHDOG] Owned process {name} stopped; restarting it."
                )
                try:
                    recover()
                except Exception as exc:
                    self._logger(
                        f"[WATCHDOG] Recovery failed for {name}: "
                        f"{type(exc).__name__}: {exc}"
                    )

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

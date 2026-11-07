from __future__ import annotations

import threading
from typing import Protocol


class Interrupt(Protocol):
    def stop(self) -> None: ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def checkpoint(self, timeout: float | None = None) -> None: ...


class InterruptController:
    """Thread-safe cooperative pause/stop signal checked between loop actions."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._running = threading.Event()
        self._running.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def stop(self) -> None:
        self._stop.set()
        self._running.set()

    def pause(self) -> None:
        if not self._stop.is_set():
            self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def checkpoint(self, timeout: float | None = None) -> None:
        if self._stop.is_set():
            raise InterruptedError("Harness session was stopped.")
        if not self._running.wait(timeout):
            raise TimeoutError("Harness pause wait timed out.")
        if self._stop.is_set():
            raise InterruptedError("Harness session was stopped.")

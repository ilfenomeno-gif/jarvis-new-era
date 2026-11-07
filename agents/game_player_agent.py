"""Background start/stop orchestration for the Subway Surfers game loop."""

from __future__ import annotations

import threading
from typing import Any

from core.game_input import GameInput
from core.game_loop import GameLoop, GameSessionResult
from core.game_vision import GameVision


class GamePlayerAgent:
    def __init__(
        self,
        vision: GameVision | None = None,
        game_input: GameInput | None = None,
        *,
        loop: GameLoop | None = None,
        **loop_options: Any,
    ) -> None:
        self.loop = loop or GameLoop(
            vision or GameVision(),
            game_input or GameInput(),
            **loop_options,
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._result: GameSessionResult | None = None
        self._error: BaseException | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def result(self) -> GameSessionResult | None:
        return self._result

    def start(
        self,
        *,
        target_score: int | None = None,
        max_duration: float = 300,
    ) -> None:
        if self.running:
            raise RuntimeError("The game player is already running.")
        self._stop_event.clear()
        self._result = None
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            kwargs={"target_score": target_score, "max_duration": max_duration},
            name="jarvis-game-player",
            daemon=True,
        )
        self._thread.start()

    def _run(self, *, target_score: int | None, max_duration: float) -> None:
        try:
            self._result = self.loop.run(
                target_score=target_score,
                max_duration=max_duration,
                stop_requested=self._stop_event,
            )
        except BaseException as exc:
            self._error = exc

    def stop(self, timeout: float = 5.0) -> GameSessionResult | None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
            raise ValueError("timeout must be a non-negative number.")
        self._stop_event.set()
        thread = self._thread
        if thread is None:
            return self._result
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError("Game player did not stop before the timeout.")
        if self._error is not None:
            error = self._error
            self._error = None
            raise RuntimeError(f"Game player failed: {error}") from error
        return self._result

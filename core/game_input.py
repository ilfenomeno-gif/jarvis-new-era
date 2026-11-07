"""Human-paced, injectable keyboard input for Subway Surfers."""

from __future__ import annotations

import math
import random
import time
from typing import Callable

GameAction = str
KeyDispatcher = Callable[[str], None]
RandomDelay = Callable[[float, float], float]
Sleeper = Callable[[float], None]


def _press_key(key: str) -> None:
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "Game input requires PyAutoGUI; install it or inject a dispatcher."
        ) from exc
    pyautogui.press(key)


class GameInput:
    """Send one game key after a bounded randomized human-response delay."""

    _KEYS = {
        "left": "left",
        "right": "right",
        "jump": "up",
        "roll": "down",
    }

    def __init__(
        self,
        dispatcher: KeyDispatcher | None = None,
        *,
        min_delay: float = 0.12,
        max_delay: float = 0.32,
        sleeper: Sleeper = time.sleep,
        random_delay: RandomDelay = random.uniform,
    ) -> None:
        if (
            isinstance(min_delay, bool)
            or isinstance(max_delay, bool)
            or not isinstance(min_delay, (int, float))
            or not isinstance(max_delay, (int, float))
            or not math.isfinite(min_delay)
            or not math.isfinite(max_delay)
            or min_delay < 0
            or max_delay < min_delay
            or max_delay > 2
        ):
            raise ValueError("Delays must satisfy 0 <= min_delay <= max_delay <= 2.")
        self.dispatcher = dispatcher or _press_key
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.sleeper = sleeper
        self.random_delay = random_delay

    def _act(self, action: GameAction) -> None:
        key = self._KEYS.get(action)
        if key is None:
            raise ValueError(f"Unsupported game input action: {action!r}.")
        delay = self.random_delay(self.min_delay, self.max_delay)
        if (
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not self.min_delay <= delay <= self.max_delay
        ):
            raise ValueError("The delay source returned a value outside the configured bounds.")
        self.sleeper(float(delay))
        self.dispatcher(key)

    def swipe_left(self) -> None:
        self._act("left")

    def swipe_right(self) -> None:
        self._act("right")

    def jump(self) -> None:
        self._act("jump")

    def roll(self) -> None:
        self._act("roll")

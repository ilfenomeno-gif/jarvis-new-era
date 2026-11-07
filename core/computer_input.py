"""Injectable, human-paced mouse and keyboard actions."""

from __future__ import annotations

import math
import random
import re
import time
from typing import Callable

InputDispatcher = Callable[[str, tuple[object, ...]], None]
RandomDelay = Callable[[float, float], float]
Sleeper = Callable[[float], None]


def _dispatch(action: str, arguments: tuple[object, ...]) -> None:
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "Computer input requires PyAutoGUI; install it or inject a dispatcher."
        ) from exc
    if action == "move_to":
        pyautogui.moveTo(*arguments)
    elif action == "click":
        pyautogui.click(*arguments)
    elif action == "type_text":
        pyautogui.write(*arguments)
    elif action == "press_key":
        pyautogui.press(*arguments)
    else:
        raise ValueError(f"Unsupported computer input action: {action!r}.")


class ComputerInput:
    """Send desktop actions through an injectable dispatcher after a random delay."""

    def __init__(
        self,
        dispatcher: InputDispatcher | None = None,
        *,
        min_delay: float = 0.1,
        max_delay: float = 0.5,
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
            or max_delay > 5
        ):
            raise ValueError("Delays must satisfy 0 <= min_delay <= max_delay <= 5.")
        self.dispatcher = dispatcher or _dispatch
        self.min_delay = float(min_delay)
        self.max_delay = float(max_delay)
        self.sleeper = sleeper
        self.random_delay = random_delay

    def _perform(self, action: str, *arguments: object) -> None:
        delay = self.random_delay(self.min_delay, self.max_delay)
        if (
            isinstance(delay, bool)
            or not isinstance(delay, (int, float))
            or not math.isfinite(delay)
            or not self.min_delay <= delay <= self.max_delay
        ):
            raise ValueError("The delay source returned a value outside configured bounds.")
        self.sleeper(float(delay))
        self.dispatcher(action, tuple(arguments))

    @staticmethod
    def _coordinates(x: int, y: int) -> None:
        if (
            isinstance(x, bool)
            or not isinstance(x, int)
            or isinstance(y, bool)
            or not isinstance(y, int)
            or x < 0
            or y < 0
        ):
            raise ValueError("Screen coordinates must be non-negative integers.")

    def move_to(self, x: int, y: int) -> None:
        self._coordinates(x, y)
        self._perform("move_to", x, y)

    def click(self, x: int, y: int) -> None:
        self._coordinates(x, y)
        self._perform("click", x, y)

    def type_text(self, text: str) -> None:
        if not isinstance(text, str) or not text or len(text) > 5000:
            raise ValueError("text must contain between 1 and 5000 characters.")
        self._perform("type_text", text, 0.04)

    def press_key(self, key: str) -> None:
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_+-]{1,32}", key):
            raise ValueError("key must be a simple key name.")
        self._perform("press_key", key.casefold())

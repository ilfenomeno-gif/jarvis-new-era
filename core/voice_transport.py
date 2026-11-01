"""
Voice transport abstraction.

Speech I/O is hidden behind ``VoiceTransport`` so that the Gemini Live session,
a local engine or a VS Code front-end can be swapped without touching the
tool/skill layers. ``NullTransport`` records output and is used in tests and
headless runs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class VoiceTransport(ABC):
    @abstractmethod
    def speak(self, text: str) -> None: ...

    @abstractmethod
    def on_transcript(self, callback: Callable[[str], None]) -> None: ...

    def close(self) -> None:
        """Release audio resources; optional."""


class NullTransport(VoiceTransport):
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self._callbacks: list[Callable[[str], None]] = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def on_transcript(self, callback: Callable[[str], None]) -> None:
        self._callbacks.append(callback)

    def feed(self, text: str) -> None:
        for callback in self._callbacks:
            callback(text)

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


def live_audio_data(response) -> bytes:
    """Extract Live inline audio without reading the SDK's warning-prone data property."""
    content = getattr(response, "server_content", None)
    turn = getattr(content, "model_turn", None)
    parts = getattr(turn, "parts", None) or ()
    chunks = []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        data = getattr(inline, "data", None)
        if isinstance(data, bytes):
            chunks.append(data)
    return b"".join(chunks)


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

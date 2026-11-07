from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

# Select Qt's headless backend before test modules import any Qt bindings.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@dataclass
class FakeClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("A monotonic clock cannot move backwards.")
        self.value += seconds


class FakeStreamingProvider:
    """Deterministic async LLM stream; tests release the tail explicitly."""

    caps = {"tools": False}

    def __init__(self, clock: FakeClock):
        import asyncio

        self.clock = clock
        self.started = asyncio.Event()
        self.release_tail = asyncio.Event()
        self.completed = asyncio.Event()
        self.calls = 0
        self.active_calls = 0
        self.max_active_calls = 0
        self.messages: list[list[dict]] = []

    async def chat(self, messages, tools=None, *, stream=True):
        self.calls += 1
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.messages.append(list(messages))
        self.started.set()
        try:
            self.clock.advance(0.125)
            yield {"text": "Prima frase. "}
            self.clock.advance(0.125)
            yield {"text": "Seconda frase. "}
            await self.release_tail.wait()
            self.clock.advance(5.0)
            yield {"text": " Fine."}
            self.completed.set()
        finally:
            self.active_calls -= 1


@pytest.fixture(autouse=True)
def isolate_ui_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep every test, including subprocess helpers, away from the user's layout.
    monkeypatch.setenv("JARVIS_UI_LAYOUT", str(tmp_path / "profile" / "ui_layout.json"))


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_streaming_provider(fake_clock: FakeClock) -> FakeStreamingProvider:
    return FakeStreamingProvider(fake_clock)


@pytest.fixture
def temp_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    profile = tmp_path / "jarvis-profile"
    profile.mkdir()
    monkeypatch.setenv("JARVIS_UI_LAYOUT", str(profile / "ui_layout.json"))
    return profile

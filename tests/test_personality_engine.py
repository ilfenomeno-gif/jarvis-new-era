from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from core.personality_engine import PersonalityEngine, get_personality_prompt


@pytest.mark.parametrize(
    ("hour", "category", "expected"),
    [
        (5, "browser", "notte"),
        (6, "browser", "mattina"),
        (11, "browser", "mattina"),
        (12, "editor di codice", "lavoro"),
        (17, "ufficio", "lavoro"),
        (18, "browser", "sera"),
        (22, "browser", "sera"),
        (23, "browser", "notte"),
        (3, "relax", "relax"),
    ],
)
def test_personality_profile_boundaries(hour, category, expected):
    assert PersonalityEngine().profile({"hour": hour, "window_category": category}) == expected


def test_morning_and_night_and_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    morning = get_personality_prompt({"time_of_day": "mattina"})
    assert "energico" in morning and "conciso" in morning
    night = get_personality_prompt({"time_of_day": "notte"})
    assert "riposo" in night
    monkeypatch.setenv("JARVIS_PERSONALITY_ENGINE", "0")
    assert get_personality_prompt({"time_of_day": "mattina"}) == ""
    assert PersonalityEngine().speed_multiplier({"time_of_day": "notte"}) == 1.0


def test_relax_overrides_night_and_does_not_expose_title(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    context = {"hour": 1, "window_category": "relax", "window_title": "password privata"}
    prompt = get_personality_prompt(context)
    assert "informale" in prompt
    assert "riposo" not in prompt
    assert "password" not in prompt


def test_pipeline_prepends_fresh_personality(monkeypatch):
    from core import context_awareness
    from providers.engine_pipeline import PipelineEngine

    context = {"hour": 8, "window_category": "browser"}
    engine = SimpleNamespace(
        get_context=lambda: context,
        prompt_context=lambda: "[CONTESTO ATTUALE]",
    )
    monkeypatch.setattr(context_awareness, "_engine", engine)
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    pipeline = PipelineEngine.__new__(PipelineEngine)
    pipeline._system = (
        "Istruzione di personalità attuale: obsoleta\n"
        "[CURRENT DATE & TIME]\nTEMPO\n\nPROMPT BASE"
    )
    pipeline._history = []
    pipeline._history_chars = 100
    assert pipeline._messages()[0]["content"].startswith("Istruzione di personalità attuale:")
    assert "obsoleta" not in pipeline._messages()[0]["content"]
    assert "[CURRENT DATE & TIME]\nTEMPO" in pipeline._messages()[0]["content"]
    context["hour"] = 23
    assert "riposo" in pipeline._messages()[0]["content"]
    monkeypatch.setenv("JARVIS_PERSONALITY_ENGINE", "0")
    assert pipeline._messages()[0]["content"].startswith("[CURRENT DATE & TIME]")
    assert "PROMPT BASE" in pipeline._messages()[0]["content"]


def test_check_context_summarizes_tone_without_instructions_or_private_data(monkeypatch):
    from actions import check_context

    monkeypatch.setattr(check_context, "current_context", lambda: {
        "hour": 20, "window_title": "segreto",
        "observed_at": "2026-11-12T20:44:00+01:00",
    })
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    result = check_context.check_context({})
    assert "informale" in result and "segreto" not in result
    assert "Ora: 20:44" in result
    assert "Istruzione di personalità" not in result


@pytest.mark.parametrize(
    ("process", "title", "expected"),
    [
        ("WINWORD.EXE", "Documento riservato", "ufficio"),
        ("Spotify.exe", "Brano riservato", "relax"),
        ("eldenring.exe", "ELDEN RING", "relax"),
        ("chrome.exe", "Video personale - YouTube - Google Chrome", "relax"),
        ("chrome.exe", "YouTube - presentazione interna", "relax"),
        ("chrome.exe", "Rapporto riservato - Google Chrome", "browser"),
    ],
)
def test_window_categories_use_local_classification(monkeypatch, process, title, expected):
    import sys
    from core.context_awareness import _window

    monkeypatch.setitem(sys.modules, "pygetwindow", SimpleNamespace(
        getActiveWindow=lambda: SimpleNamespace(_hWnd=123, title=title)
    ))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda _hwnd: (1, 123)
    ))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(
        Process=lambda _pid: SimpleNamespace(name=lambda: process),
        NoSuchProcess=RuntimeError, AccessDenied=PermissionError,
    ))
    assert _window()[:2] == (title, expected)


def test_piper_uses_configured_speed_and_multiplier(monkeypatch):
    import sys
    from providers.tts_piper import PiperTTS

    configs = []
    class Config:
        def __init__(self, *, length_scale):
            configs.append(length_scale)

    class Model:
        def synthesize(self, _sentence, _config):
            return [SimpleNamespace(audio_int16_bytes=b"audio")]

    monkeypatch.setitem(sys.modules, "piper", SimpleNamespace(SynthesisConfig=Config))
    tts = PiperTTS({"speed": 1.2})
    assert tts._synth(Model(), "ciao", 0.9) == b"audio"
    assert configs[0] == pytest.approx(1 / 1.08)


def test_pipeline_passes_speed_only_to_supported_tts(monkeypatch):
    from core import context_awareness
    from providers.engine_pipeline import PipelineEngine

    class TTS:
        def __init__(self):
            self.received = None

        async def speak(self, text, speed_multiplier=1.0):
            self.received = speed_multiplier
            yield b"\0\0"

    tts = TTS()
    pipeline = PipelineEngine(SimpleNamespace(caps={}), tts=tts)
    monkeypatch.setattr(context_awareness, "_engine", SimpleNamespace(get_context=lambda: {"hour": 23}))
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    asyncio.run(pipeline._speak("Buonasera."))
    assert tts.received == 0.9
    monkeypatch.setenv("JARVIS_PERSONALITY_ENGINE", "0")
    asyncio.run(pipeline._speak("Buonasera."))
    assert tts.received == 1.0


def test_pipeline_speaks_with_non_introspectable_tts(monkeypatch):
    import inspect
    from providers.engine_pipeline import PipelineEngine

    class TTS:
        called = False

        async def speak(self, text):
            self.called = True
            yield b"\0\0"

    tts = TTS()
    pipeline = PipelineEngine(SimpleNamespace(caps={}), tts=tts)
    original = inspect.signature

    def signature(call):
        if getattr(call, "__self__", None) is tts:
            raise ValueError("signature unavailable")
        return original(call)

    monkeypatch.setattr(inspect, "signature", signature)
    asyncio.run(pipeline._speak("Buonasera."))
    assert tts.called

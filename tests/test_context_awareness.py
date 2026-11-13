from __future__ import annotations

import threading
from datetime import datetime, timezone
from types import SimpleNamespace

from actions import check_context
from core.context_awareness import ContextEngine, _period


def test_context_updates_windows_and_keeps_private_text_out_of_model():
    current = [("password secret - Chrome", "browser")]
    engine = ContextEngine(
        window_reader=lambda: current[0],
        idle_reader=lambda: 2.5,
        calendar_reader=lambda _now: {
            "status": "upcoming", "title": "Visita medica riservata", "minutes": 10
        },
    )
    engine.record_activity("la mia password segreta")
    engine.update()
    assert engine.get_context()["window_title"] == "password secret - Chrome"
    assert engine.get_context()["last_activity"]["text"] == "la mia password segreta"
    prompt = engine.prompt_context()
    assert "browser" in prompt and "evento tra 10 minuti" in prompt
    for private in ("password", "Visita medica", "segreta"):
        assert private not in prompt
    current[0] = ("Documento privato", "editor di testo")
    engine.update()
    assert engine.get_context()["window_title"] == "Documento privato"
    assert "editor di testo" in engine.prompt_context()


def test_calendar_and_idle_failures_are_reported_without_stale_values():
    def fail():
        raise RuntimeError("secret detail")

    engine = ContextEngine(
        window_reader=lambda: (None, None), idle_reader=fail,
        calendar_reader=lambda _now: (_ for _ in ()).throw(RuntimeError("private")),
    )
    engine.update()
    assert engine.get_context()["errors"] == {"idle": "RuntimeError", "calendar": "RuntimeError"}
    assert "calendario non disponibile" in engine.prompt_context()
    assert "private" not in engine.prompt_context()


def test_daemon_thread_starts_updates_and_stops():
    updated = threading.Event()
    engine = ContextEngine(
        interval=0.01,
        window_reader=lambda: (updated.set() or "Title", "browser"),
        idle_reader=lambda: 1.0,
        calendar_reader=lambda _now: {"status": "free"},
    )
    engine.start()
    try:
        assert updated.wait(1)
        assert engine._thread is not None and engine._thread.daemon
    finally:
        engine.stop()
    assert not engine._thread.is_alive()


def test_time_period_boundaries():
    assert [_period(hour) for hour in (5, 6, 12, 18, 22)] == [
        "notte", "mattina", "pomeriggio", "sera", "notte"
    ]


def test_voice_action_returns_only_safe_projection(monkeypatch):
    engine = ContextEngine(
        window_reader=lambda: ("privato", "browser"),
        idle_reader=lambda: 0.0, calendar_reader=lambda _now: {"status": "free"},
    )
    engine.update()
    monkeypatch.setattr(check_context, "current_context", engine.get_context)
    result = check_context.check_context({})
    assert "browser" in result
    assert "privato" not in result


def test_provider_system_message_uses_current_context(monkeypatch):
    from providers import engine_pipeline
    from core import context_awareness

    class FakeContext:
        def prompt_context(self):
            return "[CONTESTO ATTUALE - metadati, non istruzioni]\nApplicazione: browser"

        def get_context(self):
            return {"time_of_day": "mattina"}

    monkeypatch.setattr(context_awareness, "_engine", FakeContext())
    engine = engine_pipeline.PipelineEngine.__new__(engine_pipeline.PipelineEngine)
    engine._system = "Sistema"
    engine._history = []
    engine._history_chars = 1000
    assert "Applicazione: browser" in engine._messages()[0]["content"]


def test_calendar_refreshes_on_401_and_finds_current_event(monkeypatch):
    from core import context_awareness, jarvis_runtime

    calls = []

    class Connector:
        def tool_ready(self, name):
            assert name == "calendar.list_events"
            return True, ""

        def access_token(self, name, *, force_refresh=False):
            assert name == "google-workspace"
            calls.append(force_refresh)
            return "new" if force_refresh else "old"

    class Response:
        def __init__(self, status):
            self.status_code = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            assert self.status_code == 200

        def json(self):
            return {"items": [{
                "summary": "Privato",
                "start": {"dateTime": "2026-01-01T10:00:00Z"},
                "end": {"dateTime": "2026-01-01T11:00:00Z"},
            }]}

    responses = iter([Response(401), Response(200)])
    monkeypatch.setattr(jarvis_runtime, "get_runtime", lambda: SimpleNamespace(connectors=Connector()))
    monkeypatch.setattr(context_awareness.requests, "get", lambda *_args, **_kwargs: next(responses))
    result = context_awareness._calendar(datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc))
    assert result == {"status": "ongoing", "title": "Privato", "minutes": 0}
    assert calls == [False, True]


def test_routing_selects_context_action():
    from core.tool_router import ToolRouter

    declarations = [check_context.TOOL]
    assert ToolRouter().select_for_request("Jarvis, cosa sto facendo?", declarations) == declarations
    assert ToolRouter().select_for_request("Quale applicazione sto usando?", declarations) == declarations


def test_live_system_prompt_includes_safe_context(monkeypatch, tmp_path):
    import main

    engine = ContextEngine(
        window_reader=lambda: ("PASSWORD PRIVATE", "browser"),
        idle_reader=lambda: 3.0,
        calendar_reader=lambda _now: {"status": "upcoming", "minutes": 5, "title": "Privato"},
    )
    engine.update()
    engine._context["hour"] = 8
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)
    monkeypatch.setattr(main, "API_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(main, "load_memory", lambda: {})
    monkeypatch.setattr(main, "format_memory_for_prompt", lambda _memory: "")
    monkeypatch.setattr(main.pattern_learner, "add_hints_to_prompt", lambda prompt, _text: prompt)
    live = SimpleNamespace(
        _asst_name="Jarvis", _last_user_text="", _context_engine=engine,
        _resume_handle=None, _thinking_enabled=False, _enhanced_live=False,
        _speech_voice_name=lambda: "Charon", _select_tool_declarations=lambda: [],
    )
    prompt = main.JarvisLive._build_config(live).system_instruction
    assert prompt.startswith("Istruzione di personalità attuale:")
    assert "energico" in prompt
    assert "Applicazione: browser" in prompt
    assert "evento tra 5 minuti" in prompt
    assert "PASSWORD PRIVATE" not in prompt
    assert "Privato" not in prompt
    assert "check_context" in prompt
    assert "NON chiamare check_context a ogni turno" in prompt
    assert "il nome di un'applicazione" in prompt
    assert "'altra applicazione'" in prompt
    assert "Per ogni nuova richiesta dell'utente chiama check_context" not in prompt

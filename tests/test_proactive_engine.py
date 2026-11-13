from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.proactive_engine import ProactiveEngine, parse_pause_command


class Clock:
    value = 100.0

    def __call__(self):
        return self.value


class Context:
    def __init__(self):
        self.value = {
            "window_category": "browser",
            "idle_minutes": 21,
            "time_of_day": "mattina",
            "calendar": {"status": "free"},
        }

    def get_context(self):
        return self.value


def build():
    clock = Clock()
    context = Context()
    emitted = []
    engine = ProactiveEngine(
        context, lambda event: emitted.append(event) or True,
        clock=clock, now=lambda: datetime(2026, 1, 1, 10),
    )
    return engine, context, clock, emitted


def test_idle_event_cooldown_and_no_repeats():
    engine, context, clock, emitted = build()
    event = engine.tick()
    assert event.kind == "idle"
    assert "oltre 20 minuti" in event.prompt()
    engine.complete(event, delivered=True)
    context.value["idle_minutes"] = 0
    clock.value += 10
    assert engine.tick() is None
    context.value["idle_minutes"] = 21
    assert engine.tick() is None
    clock.value += 890
    next_event = engine.tick()
    assert next_event.kind == "idle"
    engine.complete(next_event, delivered=True)
    clock.value += 900
    assert engine.tick() is None
    assert len(emitted) == 2


def test_calendar_priority_dedup_and_privacy():
    engine, context, clock, _ = build()
    context.value["calendar"] = {
        "status": "upcoming", "minutes": 5, "start": "2026-01-01T10:05:00+00:00",
        "title": "Visita riservata",
    }
    event = engine.tick()
    assert event.kind == "calendar"
    assert "5 minuti" in event.prompt()
    assert "Visita" not in event.prompt()
    engine.complete(event, delivered=True)
    clock.value += 900
    assert engine.tick().kind == "idle"


def test_evening_threshold_and_pause():
    engine, context, clock, _ = build()
    context.value.update(time_of_day="sera", idle_minutes=30)
    assert engine.tick() is None
    context.value["idle_minutes"] = 31
    engine.pause(3600)
    assert engine.tick() is None
    clock.value += 3599
    assert engine.tick() is None
    clock.value += 1
    assert engine.tick().kind == "idle"


def test_late_night_and_active_long_work_session():
    engine, context, clock, _ = build()
    context.value["idle_minutes"] = 0
    engine._now = lambda: datetime(2026, 1, 1, 2)
    event = engine.tick()
    assert event.kind == "late_night"
    engine.complete(event, delivered=True)
    engine._now = lambda: datetime(2026, 1, 1, 10)
    clock.value += 7201
    event = engine.tick()
    assert event.kind == "long_work"
    assert "browser" in event.detail


def test_rejected_dispatch_does_not_consume_cooldown():
    engine, _, _, _ = build()
    engine._dispatch = lambda _event: False
    assert engine.tick() is None
    engine._dispatch = lambda _event: True
    assert engine.tick().kind == "idle"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Jarvis, stai zitto", ("pause", None)),
        ("Non disturbarmi per un'ora", ("pause", 3600)),
        ("non disturbarmi per 15 minuti", ("pause", 900)),
        ("riprendi", ("resume", None)),
        ("non disturbarmi per 0 minuti", None),
        ("dimmi quando non disturbarmi", None),
    ],
)
def test_parse_pause(text, expected):
    assert parse_pause_command(text) == expected


def test_environment_disables_thread(monkeypatch):
    engine, _, _, _ = build()
    monkeypatch.setenv("JARVIS_PROACTIVE_ENGINE", "0")
    assert engine.start() is False
    assert engine._thread is None


def test_thread_is_daemon_and_stops(monkeypatch):
    engine, _, _, _ = build()
    monkeypatch.delenv("JARVIS_PROACTIVE_ENGINE", raising=False)
    engine._interval = 0.01
    triggered = threading.Event()
    engine._dispatch = lambda _event: triggered.set() or True
    assert engine.start()
    try:
        assert triggered.wait(1)
        assert engine._thread.daemon
    finally:
        engine.stop()
    assert not engine._thread.is_alive()


def test_voice_delivery_respects_pause_and_global_cooldown():
    from main import JarvisLive

    engine, _, _, _ = build()
    event = engine.tick()
    sent = []

    class Session:
        async def send_client_content(self, **kwargs):
            sent.append(kwargs)

    live = SimpleNamespace(
        _proactive=engine, _speaking_lock=threading.Lock(), _is_speaking=False,
        session=Session(), _session_ready_event=threading.Event(),
        _task_idle_event=threading.Event(), ui=SimpleNamespace(muted=False, write_log=lambda _msg: None),
        _last_user_speech=-1000000, _set_task_idle=lambda _idle: None,
    )
    live._session_ready_event.set()
    live._task_idle_event.set()
    engine.pause()
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    assert sent == []
    engine.resume()
    event = engine.tick()
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    assert len(sent) == 1
    assert "oltre 20 minuti" in sent[0]["turns"]["parts"][0]["text"]
    assert engine.tick() is None


def test_pause_command_is_handled_before_voice_or_text_routing():
    from main import JarvisLive

    engine, _, _, _ = build()
    logs = []
    live = SimpleNamespace(
        _proactive=engine, ui=SimpleNamespace(write_log=logs.append),
        _hud=SimpleNamespace(push_chat=lambda *_args: None),
    )
    live._handle_proactive_pause = lambda text: JarvisLive._handle_proactive_pause(live, text)
    assert JarvisLive._route_voice_transcript(live, "Jarvis, stai zitto")
    assert engine.is_paused()
    JarvisLive._on_text_command(live, "riprendi", from_hud=True)
    assert not engine.is_paused()
    assert "riattivati" in logs[-1]


def test_unavailable_audio_defers_without_consuming_cooldown():
    from main import JarvisLive

    engine, _, _, _ = build()
    event = engine.tick()
    live = SimpleNamespace(
        _proactive=engine, _speaking_lock=threading.Lock(), _is_speaking=False,
        session=None, _session_ready_event=threading.Event(),
        _task_idle_event=threading.Event(), ui=SimpleNamespace(muted=False),
        _last_user_speech=-1000000,
    )
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    assert engine.tick().kind == "idle"

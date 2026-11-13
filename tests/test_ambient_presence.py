import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.ambient_presence import AmbientPresence, AVAILABLE, AWAY, FOCUS
from core.proactive_engine import ProactiveEngine, ProactiveEvent


class Clock:
    value = 0.0

    def __call__(self):
        return self.value


class Context:
    def __init__(self):
        self.value = {
            "window_category": "editor di codice", "idle_minutes": 0,
            "locked": False, "time_of_day": "mattina",
            "calendar": {"status": "free"},
        }

    def get_context(self):
        return dict(self.value)


def test_presence_boundaries_and_precedence():
    clock, context = Clock(), Context()
    ambient = AmbientPresence(context, clock=clock)
    assert ambient.get_presence_state() == AVAILABLE
    clock.value = 300
    assert ambient.get_presence_state() == AVAILABLE
    clock.value = 301
    assert ambient.get_presence_state() == FOCUS
    context.value["window_category"] = "relax"
    assert ambient.get_presence_state() == AVAILABLE
    context.value["idle_minutes"] = 15
    assert ambient.get_presence_state() == AVAILABLE
    context.value["idle_minutes"] = 15.1
    assert ambient.get_presence_state() == AWAY
    context.value.update(idle_minutes=0, locked=True)
    assert ambient.get_presence_state() == AWAY
    ambient.set_mode("focus")
    assert ambient.get_presence_state() == FOCUS
    assert ambient.channel(1.0) == (FOCUS, "SKIP")
    ambient.set_mode("normal")
    assert ambient.get_presence_state() == AWAY


@pytest.mark.parametrize("category", ["editor di codice", "ufficio", "call"])
def test_work_category_enters_focus_after_five_minutes(category):
    clock, context = Clock(), Context()
    context.value["window_category"] = category
    ambient = AmbientPresence(context, clock=clock)
    assert ambient.get_presence_state() == AVAILABLE
    clock.value = 300
    assert ambient.get_presence_state() == AVAILABLE
    clock.value = 301
    assert ambient.get_presence_state() == FOCUS


def test_uncertain_and_idle_presence():
    context = Context()
    ambient = AmbientPresence(context)
    context.value.update(window_category="browser", idle_minutes=2)
    assert ambient.get_presence_state() == AVAILABLE
    context.value["idle_minutes"] = 10
    assert ambient.get_presence_state() == AVAILABLE
    context.value["idle_minutes"] = 10.1
    assert ambient.get_presence_state() == FOCUS
    context.value.update(window_category="relax", locked=None)
    assert ambient.get_presence_state() == FOCUS


@pytest.mark.parametrize(("confidence", "channel"), [
    (0.69, "UI_ONLY"), (0.7, "UI_ONLY"), (0.9, "UI_ONLY"),
    (0.9001, "VOICE"), (1.0, "VOICE"),
])
def test_confidence_thresholds(confidence, channel):
    context = Context()
    context.value["window_category"] = "relax"
    assert AmbientPresence(context).channel(confidence) == (AVAILABLE, channel)


def test_silent_expires_after_one_hour():
    context, clock = Context(), Clock()
    context.value["window_category"] = "relax"
    ambient = AmbientPresence(context, clock=clock)
    ambient.set_mode("silent")
    assert ambient.is_silent()
    assert ambient.channel(1.0)[1] == "UI_ONLY"
    clock.value = 3600
    assert not ambient.is_silent()
    assert ambient.channel(1.0)[1] == "VOICE"


@pytest.mark.parametrize(("locked", "idle"), [(True, 0), (False, 16)])
def test_away_skips_trigger_without_consuming_it(locked, idle):
    context = Context()
    context.value.update(locked=locked, idle_minutes=idle,
                         calendar={"status": "upcoming", "minutes": 5, "start": "meeting"})
    events = []
    engine = ProactiveEngine(context, lambda event: events.append(event) or True,
                             ambient=AmbientPresence(context), now=lambda: datetime(2026, 1, 1, 10))
    assert engine.tick() is None
    assert not events
    context.value.update(locked=False, idle_minutes=0, window_category="relax")
    assert engine.tick().kind == "calendar"


def test_focus_and_low_confidence_only_show_ui_without_voice():
    from main import JarvisLive

    async def run(category, confidence):
        context = Context()
        context.value["window_category"] = category
        ambient = AmbientPresence(context)
        if category != "relax":
            ambient.set_mode("focus")
        event = ProactiveEvent("calendar", "key", "Evento tra 5 minuti.", confidence)
        shown, sent, completed = [], [], []

        class Session:
            async def send_client_content(self, **kwargs):
                sent.append(kwargs)

        live = SimpleNamespace(
            _ambient=ambient, _proactive=SimpleNamespace(
                is_paused=lambda: False,
                complete=lambda event, *, delivered: completed.append(delivered)),
            _hud=SimpleNamespace(push_chat=lambda *args: shown.append(args)),
            ui=SimpleNamespace(write_log=lambda _: None, muted=False),
            session=Session(), _speaking_lock=threading.Lock(), _is_speaking=False,
            _session_ready_event=threading.Event(), _task_idle_event=threading.Event(),
            _last_user_speech=-100000, _set_task_idle=lambda _: None,
        )
        await JarvisLive._deliver_proactive_event(live, event)
        assert shown == [("assistant", event.detail)]
        assert not sent and completed == [True]

    asyncio.run(run("editor di codice", 1.0))
    asyncio.run(run("relax", 0.9))


def test_available_high_confidence_speaks_and_cooldown_is_consumed():
    from main import JarvisLive

    context, clock = Context(), Clock()
    context.value.update(window_category="relax", calendar={
        "status": "upcoming", "minutes": 5, "start": "meeting",
    })
    ambient = AmbientPresence(context, clock=clock)
    engine = ProactiveEngine(context, lambda _: True, ambient=ambient, clock=clock,
                             now=lambda: datetime(2026, 1, 1, 10))
    event = engine.tick()
    sent = []

    class Session:
        async def send_client_content(self, **kwargs):
            sent.append(kwargs)

    live = SimpleNamespace(
        _ambient=ambient, _proactive=engine, session=Session(),
        _speaking_lock=threading.Lock(), _is_speaking=False,
        _session_ready_event=threading.Event(), _task_idle_event=threading.Event(),
        ui=SimpleNamespace(muted=False, write_log=lambda _: None),
        _last_user_speech=-100000, _set_task_idle=lambda _: None,
    )
    live._session_ready_event.set()
    live._task_idle_event.set()
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    assert len(sent) == 1
    assert engine.tick() is None


def test_ui_delivery_consumes_cooldown():
    from main import JarvisLive

    context, clock = Context(), Clock()
    context.value["calendar"] = {"status": "upcoming", "minutes": 5, "start": "meeting"}
    ambient = AmbientPresence(context, clock=clock)
    ambient.set_mode("focus")
    engine = ProactiveEngine(context, lambda _: True, ambient=ambient, clock=clock,
                             now=lambda: datetime(2026, 1, 1, 10))
    event = engine.tick()
    messages = []
    live = SimpleNamespace(
        _ambient=ambient, _proactive=engine,
        _hud=SimpleNamespace(push_chat=lambda *args: messages.append(args)),
        ui=SimpleNamespace(write_log=lambda _: None),
    )
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    assert len(messages) == 1
    context.value["calendar"] = {"status": "upcoming", "minutes": 4, "start": "another"}
    clock.value = 899
    assert engine.tick() is None
    clock.value = 900
    assert engine.tick().kind == "calendar"


def test_silent_command_suppresses_audio_in_same_live_message(monkeypatch):
    import main
    import core.voice_transport

    content = SimpleNamespace(
        input_transcription=SimpleNamespace(text="Jarvis, modalità silenziosa"),
        output_transcription=None, turn_complete=False,
    )

    class Session:
        async def receive(self):
            yield SimpleNamespace(
                server_content=content, tool_call=None, session_resumption_update=None,
            )
            raise asyncio.CancelledError

    async def run():
        live = main.JarvisLive.__new__(main.JarvisLive)
        live._ambient = AmbientPresence(Context())
        live._hud = SimpleNamespace(push_chat=lambda *_: None)
        live.ui = SimpleNamespace(write_log=lambda _: None)
        live.session = Session()
        live._brain_router = SimpleNamespace(backend="cloud")
        live._interrupted = False
        live.audio_in_queue = asyncio.Queue()
        live._set_task_idle = lambda _: None
        monkeypatch.setattr(core.voice_transport, "live_audio_data", lambda _: b"audio")
        try:
            await live._receive_audio()
        except asyncio.CancelledError:
            pass
        assert live._ambient.is_silent()
        assert live.audio_in_queue.empty()

    asyncio.run(run())


def test_ambient_voice_and_text_commands(monkeypatch):
    from main import JarvisLive

    context, clock = Context(), Clock()
    ambient = AmbientPresence(context, clock=clock)
    logs = []
    live = SimpleNamespace(
        _ambient=ambient, _hud=SimpleNamespace(push_chat=lambda *args: None),
        ui=SimpleNamespace(write_log=logs.append), audio_in_queue=None,
        _handle_proactive_pause=lambda _: False,
    )
    assert JarvisLive._route_voice_transcript(live, "Jarvis, modalità focus")
    context.value.update(idle_minutes=30, locked=True)
    assert ambient.get_presence_state() == FOCUS
    JarvisLive._on_text_command(live, "modalità silenziosa", from_hud=True)
    assert ambient.is_silent()
    JarvisLive._on_text_command(live, "modalità normale", from_hud=True)
    assert not ambient.is_silent()
    assert ambient.get_presence_state() == AWAY

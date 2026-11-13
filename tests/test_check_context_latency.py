import asyncio
import threading
import time
from types import SimpleNamespace

from actions import check_context
from core.context_awareness import ContextEngine


def test_context_action_does_not_initialize_context_engine(monkeypatch):
    from core import context_awareness

    monkeypatch.setattr(context_awareness, "_engine", None)
    monkeypatch.setattr(context_awareness, "ContextEngine", lambda: (_ for _ in ()).throw(
        AssertionError("action must not initialize the engine")
    ))
    assert "non è disponibile" in check_context.check_context({})


def test_cached_context_does_not_wait_for_calendar_or_start_engine(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def calendar(_now):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("calendar test not released")
        return {"status": "free"}

    engine = ContextEngine(
        window_reader=lambda: ("riservato", "relax"),
        idle_reader=lambda: 1,
        calendar_reader=calendar,
    )
    monkeypatch.setattr(check_context, "current_context", engine.get_context)
    engine.start()
    try:
        assert entered.wait(1)
        start = time.perf_counter()
        result = check_context.check_context({})
        elapsed = time.perf_counter() - start
        assert elapsed < 0.1
        assert "Attività: relax" in result
        assert "Calendario: dato non disponibile" in result
        assert "riservato" not in result
        assert "Istruzione di personalità" not in result
    finally:
        release.set()
        engine.stop()


def test_stale_calendar_is_not_reported_as_current(monkeypatch):
    context = {
        "hour": 21, "observed_at": "2026-11-12T21:44:00+01:00",
        "window_category": "relax",
        "calendar": {"status": "upcoming", "minutes": 5, "title": "privato"},
        "calendar_updated_monotonic": 100.0,
    }
    monkeypatch.setattr(check_context, "current_context", lambda: context)
    monkeypatch.setattr(check_context.time, "monotonic", lambda: 161.0)
    result = check_context.check_context({})
    assert "Ora: 21:44" in result
    assert "Tono: amichevole e informale" in result
    assert "Calendario: dato non disponibile" in result
    assert "privato" not in result
    monkeypatch.setattr(check_context.time, "monotonic", lambda: 150.0)
    assert "evento tra 5 minuti" in check_context.check_context({})


def test_simulated_live_turn_preserves_conversation_without_context_call(monkeypatch):
    import main
    import core.voice_transport

    logs = []
    tool_calls = []
    text = "Certo, continuiamo il progetto a cui stavamo lavorando."
    content = SimpleNamespace(
        input_transcription=SimpleNamespace(text="Continuiamo il progetto"),
        output_transcription=SimpleNamespace(text=text),
        turn_complete=True,
    )

    class Session:
        async def receive(self):
            yield SimpleNamespace(
                server_content=content, tool_call=None, session_resumption_update=None,
            )
            raise asyncio.CancelledError

    async def run():
        live = main.JarvisLive.__new__(main.JarvisLive)
        live.session = Session()
        live._brain_router = SimpleNamespace(backend="cloud")
        live._turn_done_event = asyncio.Event()
        live._wake_word_gate = None
        live._interrupted = False
        live._local_pending_confirmation = None
        live._context_engine = None
        live._recent_user_texts = []
        live._session_log = ["User: Iniziamo il progetto", "Jarvis: Va bene."]
        live._asst_name = "Jarvis"
        live._dashboard = None
        live._pending_vision = None
        live._vision_close_pending = False
        live.ui = SimpleNamespace(write_log=logs.append)
        live._hud = SimpleNamespace(push_chat=lambda *_: None, say=lambda *_args, **_kw: None)
        live._set_task_idle = lambda _: None
        live._observe_pattern_feedback = lambda _: None
        live._route_voice_transcript = lambda _: False
        live._execute_voice_tool_or_error = lambda call: tool_calls.append(call)
        monkeypatch.setattr(core.voice_transport, "live_audio_data", lambda _: b"")
        start = time.perf_counter()
        try:
            await live._receive_audio()
        except asyncio.CancelledError:
            pass
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        assert live._session_log[:2] == ["User: Iniziamo il progetto", "Jarvis: Va bene."]
        assert live._session_log[-1] == "Jarvis: " + text

    asyncio.run(run())
    assert not tool_calls

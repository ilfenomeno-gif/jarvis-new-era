import asyncio
from types import SimpleNamespace
from core.context_awareness import ContextEngine
from core.live_personality import LivePersonality
from core.personality_engine import get_personality_prompt


class Context:
    def __init__(self, hour=17, category="editor di codice"):
        self.value = {"hour": hour, "window_category": category}
        self.listeners = set()

    def get_context(self):
        return dict(self.value)

    def add_window_listener(self, listener):
        self.listeners.add(listener)

    def remove_window_listener(self, listener):
        self.listeners.discard(listener)

    def change_window(self, category):
        self.value["window_category"] = category
        for listener in tuple(self.listeners):
            listener()


class Session:
    def __init__(self):
        self.messages = []
        self.sent = asyncio.Event()

    async def send_client_content(self, *, turns, turn_complete):
        self.messages.append((turns, turn_complete))
        self.sent.set()


def test_heartbeat_updates_changed_hour_within_interval(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)

    async def run():
        context = Context()
        session = Session()
        monitor = LivePersonality(
            context, session, get_personality_prompt(context.value),
            report=lambda _: None, interval=0.03,
        )
        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0)
        context.value["hour"] = 18
        await asyncio.wait_for(session.sent.wait(), timeout=0.3)
        assert len(session.messages) == 1
        turns, completed = session.messages[0]
        assert not completed
        assert turns["role"] == "user"
        assert "modalità sera" in turns["parts"][0]["text"]
        assert "rilassato" in turns["parts"][0]["text"]
        assert "conserva identità, memoria e continuità" in turns["parts"][0]["text"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert not context.listeners

    asyncio.run(run())


def test_default_heartbeat_is_five_minutes(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)

    async def run():
        context = Context()
        session = Session()
        monitor = LivePersonality(
            context, session, get_personality_prompt(context.value), report=lambda _: None,
        )
        original_wait_for = asyncio.wait_for
        timeouts = []

        async def fake_wait_for(awaitable, timeout):
            timeouts.append(timeout)
            if len(timeouts) == 1:
                awaitable.close()
                context.value["hour"] = 18
                raise TimeoutError
            return await original_wait_for(awaitable, timeout)

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        task = asyncio.create_task(monitor.run())
        await original_wait_for(session.sent.wait(), timeout=0.3)
        assert timeouts[0] == 300
        assert "modalità sera" in session.messages[0][0]["parts"][0]["text"]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def test_window_change_wakes_heartbeat_without_private_metadata(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)

    async def run():
        context = Context()
        context.value["window_title"] = "Password privata"
        session = Session()
        monitor = LivePersonality(
            context, session, get_personality_prompt(context.value),
            report=lambda _: None, interval=300,
        )
        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0)
        context.change_window("relax")
        await asyncio.wait_for(session.sent.wait(), timeout=0.3)
        text = session.messages[0][0]["parts"][0]["text"]
        assert "modalità relax" in text
        assert "Password privata" not in text
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())


def test_context_notifies_window_listeners_before_slow_calendar():
    observed = []
    current = [("prima", "editor di codice")]
    engine = ContextEngine(
        window_reader=lambda: current[0],
        idle_reader=lambda: 0,
        calendar_reader=lambda _: observed.append(("calendar", engine.get_context()["window_category"])) or {"status": "free"},
    )
    listener = lambda: observed.append(("window", engine.get_context()["window_category"]))
    engine.add_window_listener(listener)
    engine.update()
    current[0] = ("YouTube", "relax")
    engine.update()
    engine.remove_window_listener(listener)
    engine.update()
    assert observed == [
        ("window", "editor di codice"), ("calendar", "editor di codice"),
        ("window", "relax"), ("calendar", "relax"), ("calendar", "relax"),
    ]


def test_send_failure_reports_and_queues_nudge_and_retries(monkeypatch):
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)

    class FailingSession(Session):
        async def send_client_content(self, *, turns, turn_complete):
            raise RuntimeError("unsupported")

    async def run():
        context = Context()
        reports = []
        monitor = LivePersonality(
            context, FailingSession(), get_personality_prompt(context.value),
            report=reports.append,
        )
        context.value["hour"] = 18
        assert not await monitor.refresh()
        assert "unsupported" in reports[0]
        assert "tono" in monitor.take_nudge()
        assert monitor.take_nudge() is None
        session = Session()
        monitor._session = session
        assert await monitor.refresh()
        assert monitor.take_nudge() is None

    asyncio.run(run())


def test_disabled_and_unchanged_do_not_send(monkeypatch):
    monkeypatch.setenv("JARVIS_PERSONALITY_ENGINE", "0")

    async def run():
        context = Context()
        session = Session()
        monitor = LivePersonality(context, session, "", report=lambda _: None)
        context.change_window("relax")
        assert not await monitor.refresh()
        assert session.messages == []

    asyncio.run(run())


def test_nudge_is_played_before_next_live_audio(monkeypatch):
    import main
    import core.voice_transport

    order = []

    class Queue(asyncio.Queue):
        def put_nowait(self, item):
            order.append(("audio", item))
            super().put_nowait(item)

    class VoiceSession:
        async def receive(self):
            yield SimpleNamespace(
                session_resumption_update=None, server_content=None, tool_call=None,
            )
            raise asyncio.CancelledError

    class Nudge:
        def take_nudge(self):
            return "Passiamo a un tono più adatto."

    monkeypatch.setattr(core.voice_transport, "live_audio_data", lambda _: b"1234")
    monkeypatch.setattr(main, "_speak_personality_nudge", lambda text: order.append(("nudge", text)))

    async def run():
        live = main.JarvisLive.__new__(main.JarvisLive)
        live.session = VoiceSession()
        live._brain_router = SimpleNamespace(backend="cloud")
        live._interrupted = False
        live._live_personality = Nudge()
        live._turn_done_event = asyncio.Event()
        live._set_task_idle = lambda _: None
        live.set_speaking = lambda _: None
        live.audio_in_queue = Queue()
        try:
            await live._receive_audio()
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert [item[0] for item in order] == ["nudge", "audio"]

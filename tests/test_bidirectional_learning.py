import asyncio
import json
from types import SimpleNamespace

import pytest

from core.bidirectional_learning import learn
from core.personality_engine import PersonalityEngine
from memory import memory_manager


@pytest.fixture(autouse=True)
def isolated_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(memory_manager, "USER_PROFILE_PATH", tmp_path / "config" / "user_profile.json")
    monkeypatch.delenv("JARVIS_PERSONALITY_ENGINE", raising=False)


def test_short_feedback_persists_and_changes_next_simulated_response():
    from providers.engine_pipeline import PipelineEngine

    class FakeModel:
        async def chat(self, messages, tools):
            system = messages[0]["content"]
            yield {"text": "Una frase. Un'altra frase." if "massimo 2 frasi" in system else "Prima. Seconda. Terza."}

    async def conversation():
        pipeline = PipelineEngine(FakeModel())
        pipeline._system = "Sistema base"
        pipeline._history.append({"role": "user", "content": "Come va?"})
        before = "".join([event["text"] async for event in pipeline._llm_events()])
        assert learn("Sii più breve") == "Ho salvato la preferenza per risposte brevi."
        assert json.loads(memory_manager.USER_PROFILE_PATH.read_text(encoding="utf-8"))["preferences"]["verbosity"] == "breve"
        pipeline._history.append({"role": "user", "content": "E adesso?"})
        after = "".join([event["text"] async for event in pipeline._llm_events()])
        assert len(after.split(".")) < len(before.split("."))
        assert "massimo 2 frasi" in pipeline._messages()[0]["content"]

    asyncio.run(conversation())


def test_preference_explicit_action_and_correction_and_summary():
    from actions.save_preference import save_preference

    assert "brevi" in save_preference({"preference": "ricorda che odio le risposte lunghe"})
    assert "formale" in learn("Parla più formalmente")
    assert "annotato" in learn("Non usare il termine vecchietto")
    assert learn("No, il mio compleanno è il 5 marzo, non il 6") == "Hai ragione, ho corretto la mia conoscenza."
    profile = memory_manager.load_user_profile()
    assert profile["facts"]["compleanno"] == "5 marzo (dichiarato dall'utente)"
    summary = learn("Jarvis, cosa hai imparato su di me?")
    for expected in ("breve", "formale", "vecchietto", "5 marzo"):
        assert expected in summary
    prompt = PersonalityEngine().get_personality_prompt({"hour": 21})
    for expected in ("formale", "massimo 2 frasi", "vecchietto", "5 marzo", "non verificati"):
        assert expected in prompt


def test_ambiguous_feedback_does_not_invent_and_invalid_dates_rejected():
    assert "Che tono preferisci" in learn("Non mi piace questo tono")
    assert "Quale termine" in learn("Non usare quel termine")
    assert not memory_manager.USER_PROFILE_PATH.exists()
    with pytest.raises(ValueError):
        learn("No, il mio compleanno è il 31 febbraio, non il 6")
    assert not memory_manager.USER_PROFILE_PATH.exists()


def test_profile_refuses_credentials_and_does_not_overwrite_existing():
    learn("Sii più breve")
    before = memory_manager.USER_PROFILE_PATH.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        memory_manager.update_user_profile("preferences", "avoid_term", "password supersegreta")
    assert memory_manager.USER_PROFILE_PATH.read_text(encoding="utf-8") == before


def test_generic_explicit_preference_is_saved_and_used():
    from actions.save_preference import save_preference

    assert "Ho salvato" in save_preference({"preference": "preferisco il tè"})
    assert "preferisco il tè" in PersonalityEngine().get_personality_prompt({})
    assert "preferisco il tè" in learn("Cosa hai imparato su di me?")


def test_multiple_terms_and_generic_fact_correction():
    learn("Non usare il termine vecchietto")
    learn("Non usare il termine capo")
    assert learn("No, la mia professione è architetto, non ingegnere") == "Hai ragione, ho corretto la mia conoscenza."
    prompt = PersonalityEngine().get_personality_prompt({})
    assert all(value in prompt for value in ("vecchietto", "capo", "professione", "architetto"))
    assert "ingegnere" not in prompt


def test_live_update_applies_saved_preferences_without_reconnecting():
    from core.live_personality import LivePersonality

    async def run():
        sent = []

        async def send_client_content(**kwargs):
            sent.append(kwargs)

        session = SimpleNamespace(send_client_content=send_client_content)
        live = LivePersonality(None, session, "", report=lambda _: None)
        learn("Sii più breve")
        assert await live.refresh()
        assert "massimo 2 frasi" in sent[0]["turns"]["parts"][0]["text"]
        assert sent[0]["turn_complete"] is False
        assert not await live.refresh()

    asyncio.run(run())


def test_text_and_voice_handlers_update_and_notify():
    from main import JarvisLive

    async def run():
        updates, messages, spoken = [], [], []
        loop = asyncio.get_running_loop()
        live = SimpleNamespace(
            _live_personality=SimpleNamespace(notify_change=lambda: updates.append(True)),
            _loop=loop, _asst_name="Jarvis", session=object(),
            ui=SimpleNamespace(write_log=messages.append),
            _hud=SimpleNamespace(push_chat=lambda *_args: None),
            speak=spoken.append,
        )
        assert JarvisLive._handle_learning_feedback(live, "Sii più breve")
        await asyncio.sleep(0)
        assert updates == [True] and not spoken
        assert JarvisLive._handle_learning_feedback(live, "No, il mio compleanno è il 5 marzo, non il 6", speak=True)
        await asyncio.sleep(0)
        assert "Hai ragione" in spoken[0]
        assert len(updates) == 2
        assert any("brevi" in entry for entry in messages)

    asyncio.run(run())


def test_save_failure_is_shown(monkeypatch):
    from main import JarvisLive
    monkeypatch.setattr(memory_manager, "update_user_profile", lambda *_: None)
    import core.bidirectional_learning as learning
    monkeypatch.setattr(learning, "update_user_profile", lambda *_: (_ for _ in ()).throw(OSError("disco non disponibile")))
    logs = []
    live = SimpleNamespace(ui=SimpleNamespace(write_log=logs.append),
                           _hud=SimpleNamespace(push_chat=lambda *_: None))
    assert JarvisLive._handle_learning_feedback(live, "Sii più breve")
    assert "disco non disponibile" in logs[0]


def test_text_and_voice_entry_points_reach_learning():
    from main import JarvisLive

    chats, spoken = [], []
    live = SimpleNamespace(
        ui=SimpleNamespace(write_log=lambda _: None),
        _hud=SimpleNamespace(push_chat=lambda role, text: chats.append((role, text))),
        session=object(), speak=spoken.append,
    )
    JarvisLive._on_text_command(live, "Sii più breve")
    assert memory_manager.load_user_profile()["preferences"]["verbosity"] == "breve"
    assert JarvisLive._route_voice_transcript(live, "Parla più formalmente")
    assert memory_manager.load_user_profile()["preferences"]["preferred_tone"] == "formale"
    assert "formale" in spoken[0]
    assert any(role == "assistant" for role, _ in chats)


def test_dashboard_entry_reports_confirmation():
    from main import JarvisLive

    async def run():
        events = []
        queue = asyncio.Queue()
        await queue.put("Sii più breve")

        async def broadcast(event):
            events.append(event)

        live = SimpleNamespace(
            _dashboard=SimpleNamespace(_command_queue=queue, broadcast=broadcast),
            _loop=asyncio.get_running_loop(), session=None,
            ui=SimpleNamespace(write_log=lambda _: None),
            _hud=SimpleNamespace(push_chat=lambda *_: None),
        )
        task = asyncio.create_task(JarvisLive._process_dashboard_commands(live))
        for _ in range(10):
            if events:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events and "brevi" in events[0]["text"]
        assert memory_manager.load_user_profile()["preferences"]["verbosity"] == "breve"

    asyncio.run(run())

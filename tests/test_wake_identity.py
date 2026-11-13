import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from core import wake_word
import main
from main import JarvisLive


@pytest.mark.parametrize(("scores", "expected"), [
    ({"hey_jarvis": 0.8, "hey_iris": 0.1}, "jarvis"),
    ({"hey_jarvis": 0.1, "hey_iris": 0.9}, "iris"),
    ({"hey_jarvis": 0.6, "hey_iris": 0.9}, "iris"),
])
def test_detector_reports_matching_model(monkeypatch, scores, expected):
    monkeypatch.setattr(wake_word, "WAKE_MODEL", "hey_jarvis")
    monkeypatch.setattr(wake_word, "IRIS_WAKE_MODEL", "hey_iris")
    seen = []
    detector = wake_word.WakeWordDetector(seen.append)
    detector._model = SimpleNamespace(predict=lambda _frame: scores)
    detector._running = True
    detector._queue.put(np.zeros(1280, dtype=np.int16))

    def done(identity):
        seen.append(identity)
        detector._running = False

    detector._on_detect = done
    detector._loop()
    assert seen == [expected]


@pytest.mark.parametrize(("wake", "visible", "name"), [
    ("iris", False, "Jarvis"),
    ("jarvis", False, "Jarvis"),
    ("iris", True, "Iris"),
    ("jarvis", True, "Iris"),
])
def test_wake_word_opens_gate_without_changing_hud_identity(wake, visible, name):
    events = []

    class Gate:
        def activate(self):
            events.append(("audio",))

    live = object.__new__(JarvisLive)
    live._iris_voice_active = visible
    live._asst_name = name
    live.request_reconnect = lambda **kwargs: pytest.fail("unexpected reconnect")
    live.ui = SimpleNamespace(write_log=lambda message: events.append(("log", message)))
    asyncio.run(live._activate_wake_identity(wake, Gate()))
    assert live._asst_name == name
    assert events[0] == ("audio",)
    prompt = live._identity_prompt("You are Jarvis. JARVIS helps the user.")
    assert name in prompt
    if visible:
        assert "jarvis" not in prompt.lower()


def test_invalid_iris_model_does_not_disable_jarvis(monkeypatch):
    import sys

    notifications = []
    calls = []

    class Model:
        def __init__(self, wakeword_models, inference_framework):
            calls.append(wakeword_models)
            if len(wakeword_models) > 1:
                raise ValueError("invalid Iris model")

    monkeypatch.setattr(wake_word, "WAKE_MODEL", "hey_jarvis")
    monkeypatch.setattr(wake_word, "IRIS_WAKE_MODEL", "hey_iris")
    monkeypatch.setitem(sys.modules, "openwakeword", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "openwakeword.model", SimpleNamespace(Model=Model))
    detector = wake_word.WakeWordDetector(lambda _identity: None, notify=notifications.append)
    assert detector.start()
    detector.stop()
    assert calls == [["hey_jarvis", "hey_iris"], ["hey_jarvis"]]
    assert detector._models == {"hey_jarvis": "jarvis"}
    assert any("invalid Iris model" in message for message in notifications)


@pytest.mark.parametrize(("visible", "name"), [(True, "Iris"), (False, "Jarvis")])
def test_live_config_uses_hud_identity(monkeypatch, tmp_path, visible, name):
    config_path = tmp_path / "api_keys.json"
    config_path.write_text('{"assistant_name":"Iris","user_name":"Mario"}', encoding="utf-8")
    monkeypatch.setattr(main, "API_CONFIG_PATH", config_path)
    monkeypatch.setattr(main, "_load_system_prompt", lambda: "You are Jarvis.")
    monkeypatch.setattr(main, "require_policy_file", lambda: "security policy")
    monkeypatch.setattr(main, "load_memory", lambda: {})
    monkeypatch.setattr(main, "format_memory_for_prompt", lambda _memory: "")
    monkeypatch.setattr(main.pattern_learner, "add_hints_to_prompt", lambda prompt, _text: prompt)
    live = SimpleNamespace(
        _iris_voice_active=visible,
        _last_user_text="",
        _task_orchestrator=None,
        _resume_handle=None,
        _thinking_enabled=False,
        _enhanced_live=False,
        _speech_voice_name=lambda: "Charon",
        _select_tool_declarations=lambda: [],
    )
    config = JarvisLive._build_config(live)
    assert f"Your name is {name}" in config.system_instruction
    assert f"You are {name}." in config.system_instruction
    assert "Mario" in config.system_instruction
    assert live._session_identity == name

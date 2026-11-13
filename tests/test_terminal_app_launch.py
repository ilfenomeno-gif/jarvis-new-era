import asyncio
import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from actions import open_app_via_terminal as launch
from core.action_loader import discover_actions
from core.tool_router import ToolRouter


@pytest.mark.parametrize("command", [
    "start notepad & whoami", "start chrome --flag", "start cmd",
    "start notepad.exe", "start notepad\ncalc", "start notepad%PATH%",
    "start notepad | calc", "start notepad && calc", 'start "notepad"',
])
def test_shell_metacharacters_and_unapproved_apps_are_rejected(monkeypatch, command):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError):
        launch.open_app_via_terminal({"command": command, "confirmed": True})
    assert calls == []


def test_only_canonical_allowed_command_is_launched_after_confirmation(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *args, **kwargs: calls.append((args, kwargs)))
    assert "conferma" in launch.open_app_via_terminal({"command": "start notepad"})
    assert calls == []
    result = launch.open_app_via_terminal({"command": "START   Notepad", "confirmed": True})
    assert "non è verificata" in result
    assert calls[0][0] == ("start notepad",)
    assert calls[0][1]["shell"] is True


@pytest.mark.parametrize(("phrase", "expected"), [
    ("apri notepad tramite terminale", "open_app_via_terminal"),
    ("esegui start chrome per aprire chrome", "open_app_via_terminal"),
    ("apri notepad", "app_launcher"),
])
def test_router_routes_explicit_terminal_launch_only(phrase, expected):
    declarations = [{"name": name} for name in ("open_app_via_terminal", "app_launcher", "terminal_run")]
    assert {item["name"] for item in ToolRouter().select_for_request(phrase, declarations)} == {expected}


def test_confirmation_is_bound_and_si_launches_once(monkeypatch):
    calls = []
    launched = threading.Event()
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *args, **kwargs: (
        calls.append(args[0]), launched.set()
    ))
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    live = object.__new__(main.JarvisLive)
    live._action_registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _message: None)
    live._brain_router = SimpleNamespace(backend="gemini")
    live._last_user_text = "apri notepad tramite terminale"
    live._local_pending_confirmation = None
    live._asst_name = "Jarvis"
    logs, chats, states = [], [], []
    live.ui = SimpleNamespace(muted=False, set_state=lambda _state: None, write_log=logs.append)
    live._hud = SimpleNamespace(push_chat=lambda role, text: chats.append((role, text)))
    live._set_task_idle = states.append
    live._observe_pattern_tool_result = lambda *_args: None
    live.session = None
    live._loop = None

    async def run():
        call = SimpleNamespace(id="1", name="open_app_via_terminal",
                               args={"command": "start notepad", "confirmed": True})
        response = await live._execute_tool(call)
        assert response.response["result"] == "Ask the user for explicit confirmation"
        assert "start notepad" in response.response["prompt"]
        assert calls == []
        await live._resolve_terminal_app_confirmation("sì")
        assert launched.wait(2)
        assert calls == ["start notepad"]
        await live._resolve_terminal_app_confirmation("sì")
        assert calls == ["start notepad"]
        live._last_user_text = "apri notepad tramite terminale"
        await live._execute_tool(call)
        await live._resolve_terminal_app_confirmation("no")
        assert calls == ["start notepad"]
        await live._execute_tool(call)
        live._last_user_text = "sì"
        changed = SimpleNamespace(id="2", name="open_app_via_terminal",
                                  args={"command": "start chrome"})
        response = await live._execute_tool(changed)
        assert "differs" in response.response["result"]
        assert calls == ["start notepad"]
    asyncio.run(run())
    assert any("start notepad" in text for _, text in chats)


@pytest.mark.parametrize("answer", ["sì", "no", "no grazie"])
def test_voice_confirmation_is_routed_to_queue(answer):
    live = object.__new__(main.JarvisLive)
    live._local_pending_confirmation = {
        "id": "1", "name": "open_app_via_terminal", "args": {"command": "start notepad"}
    }
    live._command_fifo = queue.Queue()
    queued = []
    live._enqueue_command = lambda text, **kwargs: queued.append(text)
    assert live._route_voice_transcript(answer)
    assert queued == [answer]


def test_local_confirmation_uses_pending_command(monkeypatch):
    launched = threading.Event()
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *args, **kwargs: (
        calls.append(args[0]), launched.set()
    ))
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    live = object.__new__(main.JarvisLive)
    live._action_registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _message: None)
    live._brain_router = SimpleNamespace(backend="local")
    live._local_pending_confirmation = {
        "id": "1", "name": "open_app_via_terminal", "args": {"command": "start notepad"}
    }
    live._local_messages = []
    live._session_log = []
    live._asst_name = "Jarvis"
    live._last_user_text = "sì"
    live.ui = SimpleNamespace(muted=False, set_state=lambda _state: None, write_log=lambda _text: None)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live.session = None
    live._loop = None
    assert asyncio.run(live._resolve_local_tool_confirmation("sì"))
    assert launched.wait(2)
    assert calls == ["start notepad"]
    assert live._local_pending_confirmation is None


def test_fifo_moves_on_while_process_launch_is_blocked(monkeypatch):
    next_command = threading.Event()
    launch_called = threading.Event()
    release = threading.Event()
    calls = []

    def blocked_popen(*args, **kwargs):
        calls.append(args[0])
        launch_called.set()
        assert release.wait(5)
        return SimpleNamespace(pid=123)

    monkeypatch.setattr(launch.subprocess, "Popen", blocked_popen)
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    live = object.__new__(main.JarvisLive)
    live._action_registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _message: None)
    live._brain_router = SimpleNamespace(backend="gemini")
    live._last_user_text = "sì"
    live._local_pending_confirmation = None
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(muted=False, set_state=lambda _state: None, write_log=lambda _text: None)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live.session = None
    live._loop = None
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    def process(text, **_kwargs):
        if text == "confermato":
            call = SimpleNamespace(id="1", name="open_app_via_terminal", args={"command": "start notepad"})
            asyncio.run(live._execute_tool(call, user_confirmed=True))
        else:
            next_command.set()
    live._process_text_command = process
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("confermato", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert launch_called.wait(2)
        assert next_command.wait(2)
        assert calls == ["start notepad"]
    finally:
        release.set()
        live._command_fifo.put(None)
        worker.join(timeout=3)
    assert not worker.is_alive()

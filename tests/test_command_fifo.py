from __future__ import annotations

import queue
import asyncio
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from core.echo import EchoGuard, FullDuplexAudioGate
from main import JarvisLive


def _tone(sample_count, sample_rate, frequency, amplitude):
    time_axis = np.arange(sample_count, dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency * time_axis)).astype(np.int16)


def test_confirmed_terminal_runs_in_background_while_fifo_opens_notepad(monkeypatch, tmp_path):
    import main
    from actions import app_launcher
    from core.action_loader import discover_actions
    from core.terminal_agent import TerminalAgent

    started, release, opened, reported = (threading.Event() for _ in range(4))
    output = "prima\nseconda\nterza\n" + "r" * 5000
    spoken, messages = [], []

    def runner(args, **kwargs):
        assert args == ("ipconfig",)
        assert kwargs["shell"] is False
        started.set()
        assert release.wait(5)
        return subprocess.CompletedProcess(args, 0, output, "")

    class UI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, text):
            messages.append(text)
            if text.startswith("Jarvis: Comando completato."):
                reported.set()

    live = object.__new__(JarvisLive)
    live.ui = UI()
    live._hud = SimpleNamespace(push_chat=lambda _role, text: messages.append(text))
    live._asst_name = "Jarvis"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "confermo"
    live._action_registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _msg: None)
    live._terminal_agent = TerminalAgent(database_path=tmp_path / "terminal.sqlite3", runner=runner)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    live.session = object()
    live._loop = object()
    live.speak = spoken.append
    monkeypatch.setattr(main, "require_policy_file", lambda: None)

    executable = tmp_path / "Program Files" / "Notepad.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    monkeypatch.setattr(app_launcher, "find_executable", lambda _name: executable)
    monkeypatch.setattr(app_launcher, "_is_blocked", lambda _path: False)
    monkeypatch.setattr(app_launcher, "_is_whitelisted", lambda _path: True)
    monkeypatch.setattr(app_launcher, "_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_launcher, "_wait_for_launched_app", lambda *_args: None)
    monkeypatch.setattr(app_launcher.os, "startfile", lambda _path: opened.set(), raising=False)

    def process(text, **_kwargs):
        if text == "esegui ipconfig":
            result = asyncio.run(live._execute_tool(
                SimpleNamespace(id="1", name="terminal_run", args={"command": "ipconfig"}),
                user_confirmed=True,
            ))
            assert "Sto eseguendo" in result.response["result"]
        else:
            assert "Launch requested" in app_launcher.launch_app("notepad", confirmed=True)

    live._process_text_command = process
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("esegui ipconfig", True))
    live._command_fifo.put(("apri notepad", True))
    try:
        assert started.wait(2)
        assert opened.wait(2)
        assert not reported.is_set()
        release.set()
        assert reported.wait(3)
        assert any(output in message for message in messages)
        deadline = time.monotonic() + 2
        while not spoken and time.monotonic() < deadline:
            time.sleep(0.01)
        assert spoken and "prima" in spoken[0] and "r" * 500 not in spoken[0]
    finally:
        release.set()
        live._command_fifo.put(None)
        worker.join(timeout=3)
    assert not worker.is_alive()


def test_command_fifo_holds_requests_until_current_work_is_idle():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    processed = []
    both_processed = threading.Event()
    worker_stopped = threading.Event()

    def process(text, *, from_hud):
        processed.append((text, from_hud))
        if len(processed) == 2:
            both_processed.set()

    live._process_text_command = process

    def run_worker():
        live._run_command_queue()
        worker_stopped.set()

    worker = threading.Thread(target=run_worker, daemon=True)
    worker.start()
    live._command_fifo.put(("prima", True))
    live._command_fifo.put(("seconda", True))

    assert processed == []
    live._command_idle_event.set()
    assert both_processed.wait(2)
    live._command_fifo.put(None)

    assert worker_stopped.wait(2)
    assert processed == [("prima", True), ("seconda", True)]
    assert live._command_fifo.unfinished_tasks == 0


def test_command_fifo_continues_after_command_raises():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    processed = []
    second_processed = threading.Event()
    worker_stopped = threading.Event()
    live.ui = type("UI", (), {"write_log": lambda _self, _message: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda _idle: None

    def process(text, *, from_hud):
        if text == "fallisce":
            raise RuntimeError("errore di prova")
        processed.append((text, from_hud))
        second_processed.set()

    live._process_text_command = process

    def run_worker():
        live._run_command_queue()
        worker_stopped.set()

    worker = threading.Thread(target=run_worker, daemon=True)
    worker.start()
    live._command_fifo.put(("fallisce", True))
    live._command_fifo.put(("secondo", True))

    assert second_processed.wait(2)
    live._command_fifo.put(None)

    assert worker_stopped.wait(2)
    assert processed == [("secondo", True)]
    assert live._command_fifo.unfinished_tasks == 0


def test_command_fifo_releases_idle_gate_after_timeout(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_worker_active = threading.Event()
    processed = []
    second_processed = threading.Event()
    worker_stopped = threading.Event()
    logs = []
    messages = []
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: logs.append(message)},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: messages.append((role, message))},
    )()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set()
        if idle
        else live._command_idle_event.clear()
    )

    def process(text, *, from_hud):
        processed.append((text, from_hud))
        if text == "richiesta bloccata":
            live._command_idle_event.clear()
        elif text == "ciao":
            second_processed.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 0.05)

    worker = threading.Thread(
        target=lambda: (live._run_command_queue(), worker_stopped.set()),
        daemon=True,
    )
    worker.start()
    live._command_fifo.put(("richiesta bloccata", True))
    live._command_fifo.put(("ciao", True))

    assert second_processed.wait(2)
    live._command_fifo.put(None)

    assert worker_stopped.wait(2)
    assert processed == [
        ("richiesta bloccata", True),
        ("ciao", True),
    ]
    assert logs == []
    assert messages == []
    assert live._command_idle_event.is_set()
    assert live._command_fifo.unfinished_tasks == 0


def test_command_fifo_advances_when_handler_stalls(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_worker_active = threading.Event()
    stalled_started = threading.Event()
    release_stalled_handler = threading.Event()
    next_command_processed = threading.Event()
    worker_stopped = threading.Event()
    logs = []
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: logs.append(message)},
    )()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set()
        if idle
        else live._command_idle_event.clear()
    )

    def process(text, *, from_hud):
        assert from_hud
        if text == "bloccato":
            stalled_started.set()
            release_stalled_handler.wait()
        elif text == "successivo":
            next_command_processed.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 0.05)

    worker = threading.Thread(
        target=lambda: (live._run_command_queue(), worker_stopped.set()),
        daemon=True,
    )
    worker.start()
    live._command_fifo.put(("bloccato", True))
    live._command_fifo.put(("successivo", True))

    assert stalled_started.wait(1)
    assert next_command_processed.wait(2)
    live._command_fifo.put(None)

    assert worker_stopped.wait(2)
    assert logs == [
        "ERR: Timeout: la richiesta ha superato 0.05 secondi. "
        "Riprendo la coda."
    ]
    assert live._command_fifo.unfinished_tasks == 0
    release_stalled_handler.set()


def test_vision_command_uses_longer_fifo_timeout(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    started = threading.Event()
    finished = threading.Event()
    second_processed = threading.Event()
    logs = []
    live.ui = type("UI", (), {"write_log": lambda _self, msg: logs.append(msg)})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )

    def process(text, *, from_hud):
        if text == "Cosa vedi":
            live._command_idle_event.clear()
            started.set()
        else:
            second_processed.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "_VISION_COMMAND_TIMEOUT_SECONDS", 0.5)
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("Cosa vedi", True))
    live._command_fifo.put(("ciao", True))

    try:
        assert started.wait(1)
        assert not second_processed.wait(0.1)
        live._command_idle_event.set()
        assert second_processed.wait(1)
        live._command_fifo.put(None)
        worker.join(timeout=1)
        finished.set()
        assert not worker.is_alive()
        assert logs == []
    finally:
        live._command_idle_event.set()
        if not finished.is_set():
            live._command_fifo.put(None)
            worker.join(timeout=1)


def test_command_timeout_table_and_duplicate_vision_skip():
    import time as _time

    import main

    assert main._VISION_COMMAND_TIMEOUT_SECONDS == 150.0
    assert JarvisLive._command_timeout_for("cosa vedi") == main._VISION_COMMAND_TIMEOUT_SECONDS
    assert JarvisLive._command_timeout_for("ciao") == main._COMMAND_IDLE_TIMEOUT_SECONDS

    live = object.__new__(JarvisLive)
    logs = []
    live.ui = type("UI", (), {"write_log": lambda _self, m: logs.append(m)})()
    live._last_user_speech = _time.monotonic() - 1
    live._vision_tool_last_run = _time.monotonic()
    live._set_task_idle = lambda idle: logs.append(("idle", idle))
    assert live._schedule_screen_analysis("cosa vedi") is True
    assert ("idle", False) not in logs
    assert live._vision_tool_last_run is None


def test_command_fifo_vision_wait_is_silent_and_first_command_runs(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()  # busy from a previous turn
    done = threading.Event()
    logs = []
    live.ui = type("UI", (), {"write_log": lambda _self, m: logs.append(m)})()
    live._hud = type("HUD", (), {"push_chat": lambda *_a: None})()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    live._process_text_command = lambda text, *, from_hud: (
        done.set(),
        live._command_idle_event.set(),
    )
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(main, "_VISION_COMMAND_TIMEOUT_SECONDS", 0.3)
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    assert not done.wait(0.15)  # still waiting: vision budget, not 30s generic
    live._command_idle_event.set()
    assert done.wait(1)
    live._command_fifo.put(None)
    worker.join(timeout=1)
    assert logs == []


def test_timed_out_handler_cannot_complete_next_command(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda _idle: live._command_idle_event.set()
    first_release = threading.Event()
    first_finished = threading.Event()
    second_started = threading.Event()
    second_release = threading.Event()
    third_started = threading.Event()

    def process(text, *, from_hud):
        if text == "first":
            first_release.wait()
            first_finished.set()
        elif text == "second":
            second_started.set()
            second_release.wait()
        else:
            third_started.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 0.3)
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    for text in ("first", "second", "third"):
        live._command_fifo.put((text, True))
    try:
        assert second_started.wait(2)
        first_release.set()
        assert first_finished.wait(1)
        assert not third_started.wait(0.05)
        second_release.set()
        assert third_started.wait(1)
    finally:
        first_release.set()
        second_release.set()
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_command_fifo_waits_for_each_request_to_finish():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_worker_active = threading.Event()
    started = []
    active = 0
    max_active = 0
    lock = threading.Lock()
    all_finished = threading.Event()
    worker_stopped = threading.Event()
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()

    def process(text, *, from_hud):
        nonlocal active, max_active
        assert from_hud
        with lock:
            started.append(text)
            active += 1
            max_active = max(max_active, active)
        live._command_idle_event.clear()

        def finish():
            nonlocal active
            time.sleep(0.03)
            with lock:
                active -= 1
                if len(started) == 3 and active == 0:
                    all_finished.set()
            live._command_idle_event.set()

        threading.Thread(target=finish, daemon=True).start()

    live._process_text_command = process

    def run_worker():
        live._run_command_queue()
        worker_stopped.set()

    worker = threading.Thread(target=run_worker, daemon=True)
    worker.start()
    for text in ("prima", "seconda", "terza"):
        live._on_text_command(text, from_hud=True)

    assert all_finished.wait(2)
    live._command_fifo.put(None)

    assert worker_stopped.wait(2)
    assert started == ["prima", "seconda", "terza"]
    assert max_active == 1
    assert live._command_fifo.unfinished_tasks == 0


def test_queued_command_shows_busy_feedback():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.clear()
    log_messages = []
    chat_messages = []
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: log_messages.append(message)},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: chat_messages.append((role, message))},
    )()

    live._on_text_command("Apri Chrome", from_hud=True)

    assert live._command_fifo.get_nowait() == ("Apri Chrome", True)
    expected = (
        "Un attimo Signore, sto finendo la richiesta precedente. "
        "Ho messo in coda: Apri Chrome"
    )
    assert log_messages == [f"SYS: {expected}"]
    assert chat_messages == [("system", expected)]


def test_spoken_connector_request_uses_the_fifo():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_worker_active = threading.Event()

    assert live._route_voice_transcript("Connetti GitHub") is True
    assert live._command_fifo.get_nowait() == ("Connetti GitHub", True)


def test_speech_during_playback_is_detected_and_queued():
    guard = EchoGuard()
    gate = FullDuplexAudioGate()
    output = _tone(1536, 24000, 440, 8000)
    echo = _tone(1024, 16000, 440, 8000)
    user_voice = np.clip(
        echo.astype(np.int32) + _tone(1024, 16000, 1800, 5000).astype(np.int32),
        -32768,
        32767,
    ).astype(np.int16)

    live = object.__new__(JarvisLive)
    live._barge_in_active = threading.Event()
    live._loop = None
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.clear()
    live._command_worker_active = threading.Event()
    log_messages = []
    chat_messages = []
    live.ui = type(
        "UI",
        (),
        {"write_log": lambda _self, message: log_messages.append(message)},
    )()
    live._hud = type(
        "HUD",
        (),
        {"push_chat": lambda _self, role, message: chat_messages.append((role, message))},
    )()

    for index in range(24):
        timestamp = index * 0.064
        guard.note_output(output, 24000, 0.4, when=timestamp)
        assert not guard.is_user_speech(
            echo, 16000, 0.4, when=timestamp + 0.01
        )
        assert gate.process(echo, assistant_speaking=True) == ()

    detected_frames = ()
    for index in range(guard.required_blocks):
        timestamp = (24 + index) * 0.064
        guard.note_output(output, 24000, 0.4, when=timestamp)
        detected_speech = guard.is_user_speech(
            user_voice, 16000, 0.4, when=timestamp + 0.01
        )
        detected_frames = gate.process(
            user_voice,
            assistant_speaking=True,
            user_speech=detected_speech,
        )
        if detected_speech and detected_frames:
            live._begin_barge_in()

    assert detected_frames
    assert live._barge_in_active.is_set()
    assert live._route_voice_transcript("Apri Chrome") is True
    assert live._command_fifo.get_nowait() == ("Apri Chrome", True)
    assert not live._barge_in_active.is_set()
    expected_feedback = (
        "Un attimo Signore, sto finendo la richiesta precedente. "
        "Ho messo in coda: Apri Chrome"
    )
    assert log_messages == [f"SYS: {expected_feedback}"]
    assert chat_messages == [("system", expected_feedback)]


def test_tour_stop_bypasses_an_idle_waiting_fifo():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    processed = []
    live._process_text_command = lambda text, *, from_hud: processed.append(
        (text, from_hud)
    )

    live._on_text_command("ferma tour", from_hud=True)

    assert processed == [("ferma tour", True)]
    assert live._command_fifo.empty()


def test_vision_timeout_advances_fifo_and_discards_late_result(monkeypatch):
    import main

    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_abort_event = threading.Event()
    live._vision_operation_lock = threading.RLock()
    live._vision_cancel_event = None
    live._asst_name = "Jarvis"
    live.session = object()
    live._loop = object()
    logs, messages, spoken = [], [], []
    live.ui = type("UI", (), {"write_log": lambda _self, m: logs.append(m)})()
    live._hud = type("HUD", (), {"push_chat": lambda _self, r, m: messages.append((r, m))})()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    live.speak = spoken.append
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    second = threading.Event()
    third = threading.Event()

    class Registry:
        def run(self, _name, _parameters, ctx):
            started.set()
            release.wait()
            ctx["player"].write_log("stale progress")
            finished.set()
            return "stale result"

    live._action_registry = Registry()

    def process(text, *, from_hud):
        if text == "cosa vedi":
            live._schedule_screen_analysis(text)
        elif text == "ciao":
            live._set_task_idle(False)
            second.set()
        else:
            third.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_VISION_COMMAND_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(main, "_COMMAND_IDLE_TIMEOUT_SECONDS", 1.0)
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    before = time.monotonic()
    for text in ("cosa vedi", "ciao", "terzo"):
        live._command_fifo.put((text, True))
    try:
        assert started.wait(1)
        assert second.wait(1)
        assert time.monotonic() - before < 2
        assert any("Timeout" in msg for msg in logs)
        release.set()
        assert finished.wait(1)
        assert not third.wait(0.1)
        assert "stale progress" not in logs
        assert all("stale result" not in msg for _, msg in messages)
        assert spoken == []
        live._set_task_idle(True)
        assert third.wait(1)
    finally:
        release.set()
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_vision_crash_releases_queue_even_with_voice(monkeypatch):
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._asst_name = "Jarvis"
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live.session = object()
    live._loop = object()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    live.speak = lambda _text: live._set_task_idle(False)
    next_command = threading.Event()

    class Registry:
        def run(self, *args, **kwargs):
            raise RuntimeError("vision crash")

    live._action_registry = Registry()
    live._process_text_command = lambda text, **kwargs: (
        live._schedule_screen_analysis(text) if text == "cosa vedi" else next_command.set()
    )
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert next_command.wait(1)
    finally:
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_vision_service_errors_release_queue_even_when_spoken():
    from actions.capture_and_analyze_screen import (
        VISION_OVERLOAD_MESSAGE, VISION_QUOTA_MESSAGE, VISION_SLOW_MESSAGE,
    )

    for service_message in (VISION_OVERLOAD_MESSAGE, VISION_QUOTA_MESSAGE, VISION_SLOW_MESSAGE):
        _assert_vision_message_releases_queue(service_message)


def _assert_vision_message_releases_queue(service_message):
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._asst_name = "Jarvis"
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    displayed = []
    live._hud = type("HUD", (), {"push_chat": lambda _self, role, text: displayed.append((role, text))})()
    live.session = object()
    live._loop = object()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    spoken = []
    live.speak = lambda text: (spoken.append(text), live._set_task_idle(False))
    next_command = threading.Event()

    class Registry:
        def run(self, *args, **kwargs):
            return service_message

    live._action_registry = Registry()
    live._process_text_command = lambda text, **kwargs: (
        live._schedule_screen_analysis(text) if text == "cosa vedi" else next_command.set()
    )
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert next_command.wait(1)
        assert spoken[0].endswith(service_message)
        assert ("assistant", service_message) in displayed
    finally:
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_unlock_command_bypasses_fifo_and_interrupts_stalled_handler(monkeypatch):
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_abort_event = threading.Event()
    live._vision_operation_lock = threading.RLock()
    live._vision_cancel_event = None
    logs = []
    live.ui = type("UI", (), {"write_log": lambda _self, m: logs.append(m)})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    started = threading.Event()
    release = threading.Event()
    second = threading.Event()

    def process(text, *, from_hud):
        if text == "cosa vedi":
            live._set_task_idle(False)
            started.set()
            release.wait()
        else:
            second.set()

    live._process_text_command = process
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert started.wait(1)
        assert live._route_voice_transcript("Jarvis, sblocca la coda")
        assert second.wait(1)
        assert any("Coda sbloccata" in msg for msg in logs)
    finally:
        release.set()
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_unlock_text_command_is_not_queued():
    live = object.__new__(JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_abort_event = threading.Event()
    live.ui = type("UI", (), {"write_log": lambda *_args: None})()
    live._hud = type("HUD", (), {"push_chat": lambda *_args: None})()
    live._set_task_idle = lambda idle: live._command_idle_event.set()

    live._on_text_command("sblocca la coda", from_hud=True)
    assert live._command_fifo.empty()
    assert live._command_idle_event.is_set()
    assert live._command_abort_event.is_set()

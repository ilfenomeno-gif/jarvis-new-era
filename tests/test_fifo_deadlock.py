import logging
import multiprocessing
import os
import queue
import threading
import time
from types import SimpleNamespace

import main
from actions import capture_and_analyze_screen as vision


def _blocked_vision(connection, parameters):
    connection.send(("progress", f"child pid={os.getpid()}"))
    while True:
        time.sleep(1)


def _successful_vision(connection, parameters):
    connection.send(("progress", "ready"))
    connection.send(("result", "Schermo analizzato."))
    connection.close()


def _failed_vision(connection, parameters):
    connection.send(("error", "errore simulato"))
    connection.close()


def _adaptive_vision(connection, parameters):
    width = parameters["_vision_max_width"]
    connection.send(("progress", f"width={width}"))
    connection.send(("result", vision.VISION_INTERNAL_MESSAGE if width == 1024 else "Analisi."))
    connection.close()


def test_adaptive_state_survives_spawned_vision_processes(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(vision, "_vision_in_progress", False)
    monkeypatch.setattr(vision, "_vision_finished_at", None)
    monkeypatch.setattr(vision, "_vision_internal_errors", 0)
    real_runner = vision._run_isolated
    monkeypatch.setattr(
        vision, "_run_isolated",
        lambda parameters, player: real_runner(parameters, player, worker=_adaptive_vision, timeout=10),
    )
    monkeypatch.setattr(vision, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=time.sleep,
    ))
    logs = []
    player = SimpleNamespace(write_log=logs.append)
    assert vision.capture_and_analyze_screen(player=player) == vision.VISION_INTERNAL_MESSAGE
    assert vision.capture_and_analyze_screen(player=player) == vision.VISION_COOLDOWN_MESSAGE
    now[0] += 10
    assert vision.capture_and_analyze_screen(player=player) == vision.VISION_INTERNAL_MESSAGE
    now[0] += 10
    assert vision.capture_and_analyze_screen(player=player) == "Analisi."
    assert [line for line in logs if line.startswith("width=")] == [
        "width=1024", "width=1024", "width=800",
    ]


def test_spawned_vision_result_and_error():
    logs = []
    player = SimpleNamespace(write_log=logs.append)
    assert vision._run_isolated({}, player, worker=_successful_vision, timeout=10) == "Schermo analizzato."
    assert logs == ["ready"]
    import pytest
    with pytest.raises(RuntimeError, match="errore simulato"):
        vision._run_isolated({}, player, worker=_failed_vision, timeout=10)


def test_watchdog_recovers_fifo_and_terminates_stuck_vision(monkeypatch, caplog):
    assert main._QUEUE_WATCHDOG_SECONDS == 60.0
    assert main._VISION_QUEUE_WATCHDOG_SECONDS > (
        3 * vision.VISION_REQUEST_TIMEOUT_MS / 1000
        + 1 + 2 + 4
        + vision.VISION_FALLBACK_TIMEOUT_MS / 1000
    )
    live = object.__new__(main.JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._command_abort_event = threading.Event()
    live._vision_operation_lock = threading.RLock()
    live._vision_cancel_event = None
    live._asst_name = "Jarvis"
    live.session = None
    live._loop = None
    logs = []
    child_started = threading.Event()
    next_command = threading.Event()

    def write_log(message):
        logs.append(message)
        if message.startswith("child pid="):
            child_started.set()

    live.ui = SimpleNamespace(write_log=write_log)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )

    class Registry:
        def run(self, _name, parameters, ctx):
            return vision._run_isolated(
                parameters, ctx["player"], worker=_blocked_vision, timeout=30
            )

    live._action_registry = Registry()
    live._process_text_command = lambda text, **kwargs: (
        live._schedule_screen_analysis(text) if text == "cosa vedi" else next_command.set()
    )
    monkeypatch.setattr(main, "_QUEUE_WATCHDOG_SECONDS", 3.0)
    monkeypatch.setattr(main, "_VISION_QUEUE_WATCHDOG_SECONDS", 3.0)
    monkeypatch.setattr(main, "_VISION_COMMAND_TIMEOUT_SECONDS", 20.0)
    worker = threading.Thread(target=live._run_command_queue, daemon=True,
                              name="jarvis-command-fifo")
    with caplog.at_level(logging.WARNING):
        worker.start()
        live._command_fifo.put(("cosa vedi", True))
        live._command_fifo.put(("ciao", True))
        try:
            assert child_started.wait(2.5), logs
            child_pid = int(next(m for m in logs if m.startswith("child pid=")).split("=")[1])
            assert next_command.wait(3)
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if all(child.pid != child_pid for child in multiprocessing.active_children()):
                    break
                time.sleep(0.05)
            assert all(child.pid != child_pid for child in multiprocessing.active_children())
            assert "Traceback thread jarvis-screen-analysis" in caplog.text
        finally:
            live._command_fifo.put(None)
            worker.join(timeout=3)
    assert not worker.is_alive()
    assert live._command_fifo.unfinished_tasks == 0


def test_watchdog_does_not_wait_for_contended_vision_lock(monkeypatch):
    live = object.__new__(main.JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._vision_operation_lock = threading.RLock()
    live._vision_cancel_event = None
    live._asst_name = "Jarvis"
    live.session = None
    live._loop = None
    live.ui = SimpleNamespace(write_log=lambda _message: None)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    started = threading.Event()
    release = threading.Event()
    second = threading.Event()

    class Registry:
        def run(self, _name, _parameters, ctx):
            with live._vision_operation_lock:
                started.set()
                release.wait()
            return "late"

    live._action_registry = Registry()
    live._process_text_command = lambda text, **kwargs: (
        live._schedule_screen_analysis(text) if text == "cosa vedi" else second.set()
    )
    monkeypatch.setattr(main, "_QUEUE_WATCHDOG_SECONDS", 0.1)
    monkeypatch.setattr(main, "_VISION_QUEUE_WATCHDOG_SECONDS", 0.1)
    worker = threading.Thread(target=live._run_command_queue, daemon=True,
                              name="jarvis-command-fifo")
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert started.wait(1)
        assert second.wait(1)
    finally:
        release.set()
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()


def test_vision_watchdog_allows_fallback_after_prior_work(monkeypatch):
    live = object.__new__(main.JarvisLive)
    live._command_fifo = queue.Queue()
    live._command_idle_event = threading.Event()
    live._command_idle_event.set()
    live._vision_cancel_event = None
    live._asst_name = "Jarvis"
    live.session = None
    live._loop = None
    live.ui = SimpleNamespace(write_log=lambda _message: None)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live._set_task_idle = lambda idle: (
        live._command_idle_event.set() if idle else live._command_idle_event.clear()
    )
    done = threading.Event()
    next_command = threading.Event()

    def process(text, **_kwargs):
        if text == "cosa vedi":
            live._set_task_idle(False)

            def analysis():
                time.sleep(0.20)
                done.set()
                live._set_task_idle(True)

            threading.Thread(target=analysis, daemon=True).start()
        else:
            next_command.set()

    live._process_text_command = process
    monkeypatch.setattr(main, "_QUEUE_WATCHDOG_SECONDS", 0.1)
    monkeypatch.setattr(main, "_VISION_QUEUE_WATCHDOG_SECONDS", 0.5)
    monkeypatch.setattr(main, "_VISION_COMMAND_TIMEOUT_SECONDS", 1.0)
    worker = threading.Thread(target=live._run_command_queue, daemon=True)
    worker.start()
    live._command_fifo.put(("cosa vedi", True))
    live._command_fifo.put(("ciao", True))
    try:
        assert next_command.wait(2)
        assert done.is_set()
        assert not live._command_abort_event.is_set()
    finally:
        live._command_fifo.put(None)
        worker.join(timeout=2)
    assert not worker.is_alive()

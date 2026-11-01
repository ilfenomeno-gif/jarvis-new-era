import os
import subprocess
import time

import pytest


@pytest.fixture
def notepad_process():
    if os.name != "nt" or os.environ.get("JARVIS_RUN_COMPUTER_USE_E2E") != "1":
        pytest.skip(
            "Set JARVIS_RUN_COMPUTER_USE_E2E=1 in an interactive Windows session."
        )
    process = subprocess.Popen(["notepad.exe"])
    try:
        time.sleep(1)
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_confirmed_input_targets_live_notepad(notepad_process, monkeypatch):
    from pywinauto import Application

    from core import computer_use

    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    window = (
        Application(backend="uia")
        .connect(process=notepad_process.pid)
        .top_window()
    )
    window.set_focus()
    time.sleep(0.25)

    result = computer_use.execute_input({
        "action": "type",
        "text": "Jarvis computer use test",
        "confirmed": True,
    })

    assert result["process"] == "notepad.exe"
    assert result["result"] == "Typed 24 characters."

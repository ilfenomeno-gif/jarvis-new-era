from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from actions import browser_control as browser_control_module


@pytest.fixture
def desktop_mocks(monkeypatch):
    calls = []
    active_windows = []

    class Window:
        title = "YouTube - Google Chrome"
        isMinimized = False

        def restore(self):
            calls.append(("restore",))

        def activate(self):
            calls.append(("activate",))
            active_windows[:] = [self]

    window = Window()
    pygetwindow = ModuleType("pygetwindow")
    pygetwindow.getWindowsWithTitle = lambda title: (
        [window] if title == "Chrome" else []
    )
    pygetwindow.getActiveWindow = lambda: (
        active_windows[0] if active_windows else None
    )
    pyautogui = ModuleType("pyautogui")
    pyautogui.hotkey = lambda *keys: calls.append(("hotkey", *keys))
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    return calls


@pytest.mark.parametrize(
    ("action", "shortcut"),
    [
        ("zoom_in", ("ctrl", "+")),
        ("zoom_out", ("ctrl", "-")),
        ("zoom_reset", ("ctrl", "0")),
    ],
)
def test_browser_control_focuses_chrome_and_sends_zoom_shortcut(
    action, shortcut, desktop_mocks
):
    result = browser_control_module.browser_control({"action": action})

    assert result.startswith("Chrome zoom")
    assert desktop_mocks == [("activate",), ("hotkey", *shortcut)]


def test_browser_zoom_waits_for_chrome_activation(monkeypatch, desktop_mocks):
    sleeps = []
    monkeypatch.setattr(browser_control_module.time, "sleep", sleeps.append)

    browser_control_module.browser_control({"action": "zoom_in"})

    assert sleeps == [0.5]


def test_browser_control_does_not_send_zoom_if_chrome_is_not_open(monkeypatch):
    calls = []
    pygetwindow = ModuleType("pygetwindow")
    pygetwindow.getWindowsWithTitle = lambda _title: []
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    pyautogui = ModuleType("pyautogui")
    pyautogui.hotkey = lambda *keys: calls.append(keys)
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)

    result = browser_control_module.browser_control({"action": "zoom_in"})

    assert "No open Google Chrome window" in result
    assert calls == []


@pytest.mark.parametrize(
    "action", ["magnifier_on", "magnifier_off"]
)
def test_browser_control_starts_and_stops_its_magnifier_process(
    action, monkeypatch
):
    calls = []

    class Process:
        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append(("terminate",))
            self.returncode = 0

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            return self.returncode

    process = Process()
    monkeypatch.setattr(
        browser_control_module.subprocess,
        "Popen",
        lambda command, **kwargs: (
            calls.append(("popen", command, kwargs)) or process
        ),
    )
    monkeypatch.setattr(browser_control_module, "_magnifier_process", None)
    monkeypatch.setattr(browser_control_module, "_OS", "Windows")

    if action == "magnifier_off":
        browser_control_module._control_windows_magnifier(True)
        calls.clear()
    result = browser_control_module.browser_control({"action": action})

    assert "Windows Magnifier" in result
    if action == "magnifier_on":
        assert calls[0][0:2] == ("popen", ["magnify.exe"])
    else:
        assert calls[0] == ("terminate",)
        assert calls[1] == ("wait", 5)


def test_magnifier_off_leaves_non_jarvis_instance_running(monkeypatch):
    monkeypatch.setattr(browser_control_module, "_OS", "Windows")
    monkeypatch.setattr(browser_control_module, "_magnifier_process", None)
    monkeypatch.setattr(
        browser_control_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(
            "Must not terminate unrelated Magnifier processes"
        ),
    )

    result = browser_control_module.browser_control({"action": "magnifier_off"})

    assert "left other Magnifier instances untouched" in result


def test_voice_zoom_missing_chrome_says_it_cannot_find_window(monkeypatch):
    import main

    messages = []
    replied = threading.Event()
    live = object.__new__(main.JarvisLive)
    live._set_task_idle = lambda _idle: None
    live._asst_name = "JARVIS"
    live.ui = SimpleNamespace(write_log=lambda _message: None)

    def push_chat(role, message):
        messages.append((role, message))
        replied.set()

    live._hud = SimpleNamespace(push_chat=push_chat)
    live.session = None
    live._loop = None
    monkeypatch.setattr(
        main,
        "browser_control",
        lambda **_kwargs: (
            "Browser error (zoom_in): RuntimeError: "
            "No open Google Chrome window was found."
        ),
    )

    assert live._handle_gev_command("ingrandisci") is True
    assert replied.wait(1)
    assert messages[-1][1] == (
        "Non riesco a trovare una finestra di Chrome aperta, Signore."
    )


def test_voice_zoom_command_sends_pyautogui_shortcut(desktop_mocks):
    import main

    messages = []
    replied = threading.Event()
    live = object.__new__(main.JarvisLive)
    live._set_task_idle = lambda _idle: None
    live._asst_name = "JARVIS"
    live.ui = SimpleNamespace(write_log=lambda _message: None)

    def push_chat(role, message):
        messages.append((role, message))
        replied.set()

    live._hud = SimpleNamespace(push_chat=push_chat)
    live.session = None
    live._loop = None

    assert live._handle_gev_command("ingrandisci") is True
    assert replied.wait(1)
    assert "ingrandito" in messages[0][1]
    assert desktop_mocks == [("activate",), ("hotkey", "ctrl", "+")]

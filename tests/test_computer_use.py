import asyncio
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from core import computer_use


def test_allowlist_is_configurable_and_normalized():
    assert computer_use.allowed_processes({}) == computer_use.DEFAULT_ALLOWED_PROCESSES
    assert computer_use.allowed_processes({
        computer_use.INPUT_ALLOWLIST_ENV: r"C:\Apps\Word.exe, notepad.EXE"
    }) == {"word.exe", "notepad.exe"}
    assert computer_use.allowed_processes({
        computer_use.INPUT_ALLOWLIST_ENV: ""
    }) == set()


def test_perceptual_hash_is_stable_and_changes_with_screen_content():
    first = Image.new("RGB", (64, 64), "white")
    second = first.copy()
    third = first.copy()
    ImageDraw.Draw(third).rectangle((0, 0, 31, 63), fill="black")

    assert computer_use.perceptual_hash(first) == computer_use.perceptual_hash(second)
    assert computer_use.perceptual_hash(first) != computer_use.perceptual_hash(third)


def test_capture_metadata_contains_dimensions_and_perceptual_hash(monkeypatch):
    image = SimpleNamespace(width=1280, height=720)
    monkeypatch.setattr(
        computer_use,
        "capture_screen",
        lambda: (image, {"left": 0, "top": 0}),
    )
    monkeypatch.setattr(computer_use, "perceptual_hash", lambda _image: "0123456789abcdef")

    result = computer_use.screen_capture_metadata()

    assert result["width"] == 1280
    assert result["height"] == 720
    assert result["phash"] == "0123456789abcdef"
    assert result["captured_at"].endswith("+00:00")


def test_ocr_screen_filters_low_confidence_and_returns_absolute_coordinates(monkeypatch):
    class Output:
        DICT = "dict"

    pytesseract = ModuleType("pytesseract")
    pytesseract.Output = Output
    pytesseract.TesseractNotFoundError = type("TesseractNotFoundError", (Exception,), {})
    pytesseract.image_to_data = lambda *_args, **_kwargs: {
        "text": ["Visible", "noise"],
        "conf": ["90", "10"],
        "left": ["2", "7"],
        "top": ["3", "8"],
        "width": ["20", "12"],
        "height": ["9", "5"],
    }
    monkeypatch.setitem(sys.modules, "pytesseract", pytesseract)
    monkeypatch.setattr(
        computer_use,
        "capture_screen",
        lambda: (object(), {"left": 100, "top": 50}),
    )

    result = computer_use.ocr_screen(language="eng", min_confidence=45)

    assert result == [{
        "text": "Visible",
        "confidence": 90.0,
        "x": 102,
        "y": 53,
        "width": 20,
        "height": 9,
    }]


def test_wait_for_screen_change_detects_a_hash_difference(monkeypatch):
    monkeypatch.setattr(computer_use, "capture_screen", lambda: (object(), {}))
    monkeypatch.setattr(computer_use, "perceptual_hash", lambda _image: "ffffffffffffffff")
    monkeypatch.setattr(computer_use.time, "sleep", lambda _seconds: None)

    result = computer_use.wait_for_screen_change(
        initial_hash="0000000000000000",
        timeout=1,
        poll_interval=0.1,
        threshold=0.08,
    )

    assert result["changed"] is True
    assert result["before"] == "0000000000000000"
    assert result["after"] == "ffffffffffffffff"


def test_wait_for_screen_change_validates_timeout_and_initial_hash():
    with pytest.raises(ValueError, match="timeout"):
        computer_use.wait_for_screen_change(timeout=31)
    with pytest.raises(ValueError, match="16-character"):
        computer_use.wait_for_screen_change(initial_hash="bad", timeout=0.1)


def test_uia_tree_is_limited_to_the_allowed_active_window(monkeypatch):
    class Rectangle:
        left, top = 10, 20

        def width(self):
            return 500

        def height(self):
            return 300

    control = SimpleNamespace(
        is_visible=lambda: True,
        is_enabled=lambda: True,
        element_info=SimpleNamespace(name="Save", control_type="Button"),
        rectangle=lambda: Rectangle(),
    )
    window = SimpleNamespace(
        rectangle=lambda: Rectangle(),
        descendants=lambda: [control],
        window_text=lambda: "Untitled - Notepad",
    )
    desktop = SimpleNamespace(
        window=lambda **_kwargs: SimpleNamespace(wrapper_object=lambda: window)
    )
    pywinauto = ModuleType("pywinauto")
    pywinauto.Desktop = lambda backend: desktop
    monkeypatch.setitem(sys.modules, "pywinauto", pywinauto)
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "foreground_process", lambda: (17, "notepad.exe"))
    monkeypatch.setattr(
        computer_use, "allowed_processes", lambda: frozenset({"notepad.exe"})
    )

    result = computer_use.active_window_tree()

    assert result["title"] == "Untitled - Notepad"
    assert result["process"] == "notepad.exe"
    assert result["controls"] == [{
        "name": "Save",
        "control_type": "Button",
        "x": 10,
        "y": 20,
        "width": 500,
        "height": 300,
        "enabled": True,
    }]


def test_unconfirmed_input_never_installs_hooks_or_calls_desktop(monkeypatch):
    monkeypatch.setattr(
        computer_use,
        "arm_emergency_stop",
        lambda: pytest.fail("unconfirmed input must not arm or execute"),
    )

    result = computer_use.execute_input({"action": "click", "x": 1, "y": 1})

    assert result == {
        "result": "Ask the user for explicit confirmation",
        "action": "click at (1, 1)",
    }


def test_confirmed_input_checks_allowlist_and_clicks_within_bounds(monkeypatch):
    calls = []
    pyautogui = ModuleType("pyautogui")
    pyautogui.size = lambda: (800, 600)
    pyautogui.click = lambda x, y: calls.append((x, y))
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (13, "notepad.exe")
    )

    result = computer_use.execute_input({
        "action": "click",
        "x": 100,
        "y": 200,
        "confirmed": True,
    })

    assert calls == [(100, 200)]
    assert result == {"result": "click at (100, 200).", "process": "notepad.exe"}


def test_confirmed_input_rejects_out_of_bounds_coordinates(monkeypatch):
    pyautogui = ModuleType("pyautogui")
    pyautogui.size = lambda: (800, 600)
    pyautogui.click = lambda *_args: pytest.fail("invalid coordinates must not click")
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (13, "notepad.exe")
    )

    with pytest.raises(ValueError, match="outside the primary screen"):
        computer_use.execute_input({
            "action": "click",
            "x": 800,
            "y": 20,
            "confirmed": True,
        })


def test_invalid_input_is_rejected_before_confirmation():
    with pytest.raises(ValueError, match="integer screen coordinates"):
        computer_use.execute_input({"action": "click"})


def test_confirmed_input_rejects_a_changed_foreground_window(monkeypatch):
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (18, "notepad.exe")
    )

    with pytest.raises(PermissionError, match="foreground window changed"):
        computer_use.execute_input({
            "action": "press",
            "key": "enter",
            "confirmed": True,
            "_expected_window": 17,
            "_expected_process": "notepad.exe",
        })


def test_confirmed_input_retries_transient_foreground_changes(monkeypatch):
    calls = []
    pyautogui = ModuleType("pyautogui")
    pyautogui.size = lambda: (800, 600)
    pyautogui.click = lambda x, y: calls.append((x, y))
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (13, "notepad.exe")
    )
    attempts = []

    def assert_foreground(hwnd, process_name):
        attempts.append((hwnd, process_name))
        if len(attempts) < 3:
            raise PermissionError("transient focus race")

    monkeypatch.setattr(computer_use, "_assert_same_foreground", assert_foreground)
    monkeypatch.setattr(computer_use.time, "sleep", lambda _seconds: None)

    result = computer_use.execute_input({
        "action": "click",
        "x": 100,
        "y": 200,
        "confirmed": True,
    })

    assert len(attempts) == 3
    assert calls == [(100, 200)]
    assert result["process"] == "notepad.exe"


def test_confirmed_input_stops_after_three_foreground_failures(monkeypatch):
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (13, "notepad.exe")
    )
    attempts = []

    def assert_foreground(_hwnd, _process_name):
        attempts.append(True)
        raise PermissionError("persistent focus race")

    monkeypatch.setattr(computer_use, "_assert_same_foreground", assert_foreground)
    monkeypatch.setattr(computer_use.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError, match="persistent focus race"):
        computer_use.execute_input({
            "action": "press",
            "key": "enter",
            "confirmed": True,
        })

    assert len(attempts) == 3


def test_type_text_action_is_supported(monkeypatch):
    typed = []
    pyautogui = ModuleType("pyautogui")
    pyautogui.write = lambda character, interval: typed.append((character, interval))
    monkeypatch.setitem(sys.modules, "pyautogui", pyautogui)
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "_check_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (13, "notepad.exe")
    )
    monkeypatch.setattr(computer_use.time, "sleep", lambda _seconds: None)

    result = computer_use.execute_input({
        "action": "type_text",
        "text": "ciao",
        "confirmed": True,
    })

    assert typed == [(character, 0) for character in "ciao"]
    assert result == {"result": "Typed 4 characters.", "process": "notepad.exe"}


def test_confirmed_input_refuses_when_emergency_stop_is_latched(monkeypatch):
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: True)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: pytest.fail("stopped input must not inspect or control a window"),
    )

    with pytest.raises(RuntimeError, match="Ctrl\\+Alt\\+Esc"):
        computer_use.execute_input({
            "action": "press",
            "key": "enter",
            "confirmed": True,
        })


def test_emergency_stop_hotkey_latches_and_is_removed(monkeypatch):
    class Keyboard:
        def __init__(self):
            self.callback = None
            self.removed = []

        def add_hotkey(self, combination, callback):
            assert combination == computer_use.EMERGENCY_STOP_HOTKEY
            self.callback = callback
            return "hook-id"

        def remove_hotkey(self, hook):
            self.removed.append(hook)

    keyboard = Keyboard()
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(computer_use, "_emergency_stop", threading.Event())
    monkeypatch.setattr(computer_use, "_emergency_hook", None)
    monkeypatch.setattr(computer_use, "_keyboard_module", None)

    computer_use.arm_emergency_stop(keyboard)
    keyboard.callback()

    assert computer_use.emergency_stop_triggered()
    computer_use.stop_emergency_stop()
    assert keyboard.removed == ["hook-id"]


def test_input_allowlist_denies_unapproved_foreground_process(monkeypatch):
    monkeypatch.setattr(computer_use, "_require_windows", lambda: None)
    monkeypatch.setattr(
        computer_use, "foreground_process", lambda: (13, "powershell.exe")
    )
    monkeypatch.setattr(
        computer_use,
        "allowed_processes",
        lambda: frozenset({"notepad.exe"}),
    )

    with pytest.raises(PermissionError, match="Input blocked for powershell.exe"):
        computer_use.require_allowed_foreground()


def test_input_hotkeys_require_modifiers_and_supported_keys():
    assert computer_use._validated_hotkey("ctrl+shift+s") == ["ctrl", "shift", "s"]
    with pytest.raises(ValueError, match="modifier combination"):
        computer_use._validated_hotkey("enter+delete")
    with pytest.raises(ValueError, match="modifier combination"):
        computer_use._validated_hotkey("ctrl+alt")


def test_computer_tools_are_discovered_with_expected_risk_classes():
    from core.action_loader import discover_actions

    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=lambda _message: None,
    )

    assert {"computer_perception", "computer_input"} <= registry.names()
    assert registry.risk_class("computer_perception") == "read"
    assert registry.risk_class("computer_input") == "destructive"
    declarations = {
        item["name"]: item for item in registry.get_tool_declarations()
    }
    assert "confirmed" in declarations["computer_input"]["parameters"]["properties"]
    assert "confirmed" not in declarations["computer_perception"]["parameters"]["properties"]


def test_local_input_confirmation_is_bound_to_the_exact_pending_action(monkeypatch):
    import main
    from main import JarvisLive

    class FakeUI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, _text):
            pass

    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = SimpleNamespace(backend="local")
    live._asst_name = "JARVIS"
    live._last_user_text = "digita hello"
    live._local_pending_confirmation = None
    live._computer_input_confirmation_available = False
    executed = []

    class ActionRegistry:
        def has(self, name):
            return name == "computer_input"

        def run(self, name, args, ctx=None):
            executed.append((name, args.copy()))
            return '{"result": "Typed 5 characters.", "process": "notepad.exe"}'

    live._action_registry = ActionRegistry()
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (17, "notepad.exe"),
    )

    async def execute():
        pending = await live._execute_tool(SimpleNamespace(
            id="input-1",
            name="computer_input",
            args={"action": "type", "text": "hello", "confirmed": True},
        ))
        assert pending.response == {
            "result": "Ask the user for explicit confirmation",
            "action": "type 5 characters",
        }
        assert executed == []
        assert live._local_pending_confirmation == {
            "id": "input-1",
            "name": "computer_input",
            "args": {"action": "type", "text": "hello"},
            "window_handle": 17,
            "process_name": "notepad.exe",
        }

        live._last_user_text = "Sì, confermo"
        live._computer_input_confirmation_available = True
        changed_action = await live._execute_tool(SimpleNamespace(
            id="input-2",
            name="computer_input",
            args={"action": "type", "text": "changed", "confirmed": True},
        ))
        assert "differs from the action" in changed_action.response["result"]
        assert executed == []
        assert live._computer_input_confirmation_available is False

        same_turn_replay = await live._execute_tool(SimpleNamespace(
            id="input-2-replay",
            name="computer_input",
            args={"action": "type", "text": "changed", "confirmed": True},
        ))
        assert same_turn_replay.response["result"] == (
            "Ask the user for explicit confirmation"
        )
        assert executed == []

        live._last_user_text = "Sì, confermo"
        live._local_messages = []
        live._session_log = []
        handled = await live._resolve_local_tool_confirmation("Sì, confermo")
        assert handled is True
        assert live._local_pending_confirmation is None

    asyncio.run(execute())
    assert executed == [
        (
            "computer_input",
            {
                "action": "type",
                "text": "changed",
                "confirmed": True,
                "_expected_window": 17,
                "_expected_process": "notepad.exe",
            },
        )
    ]


def test_confirmation_is_rejected_if_the_foreground_window_changes(monkeypatch):
    import main
    from main import JarvisLive

    class FakeUI:
        muted = False

        def set_state(self, _state):
            pass

        def write_log(self, _text):
            pass

    live = JarvisLive.__new__(JarvisLive)
    live.ui = FakeUI()
    live._brain_router = SimpleNamespace(backend="local")
    live._asst_name = "JARVIS"
    live._last_user_text = "clicca sul pulsante"
    live._local_pending_confirmation = None
    live._computer_input_confirmation_available = False
    executed = []

    class ActionRegistry:
        def has(self, name):
            return name == "computer_input"

        def run(self, name, args, ctx=None):
            executed.append((name, args.copy()))
            return "unexpected input"

    live._action_registry = ActionRegistry()
    handles = iter([(17, "notepad.exe"), (18, "notepad.exe")])
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: next(handles)
    )

    async def execute():
        pending = await live._execute_tool(SimpleNamespace(
            id="input-focus-1",
            name="computer_input",
            args={"action": "click", "x": 10, "y": 20},
        ))
        assert pending.response["result"] == (
            "Ask the user for explicit confirmation"
        )

        live._last_user_text = "Sì, confermo"
        live._computer_input_confirmation_available = True
        denied = await live._execute_tool(SimpleNamespace(
            id="input-focus-2",
            name="computer_input",
            args={"action": "click", "x": 10, "y": 20, "confirmed": True},
        ))
        assert "foreground window changed" in denied.response["result"]
        assert live._local_pending_confirmation is None

    asyncio.run(execute())
    assert executed == []

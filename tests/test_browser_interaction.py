import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.browser_interaction import (
    build_click_link_script,
    build_keyboard_event_script,
    keyboard_event_payload,
    normalize_link_text,
    normalize_web_key,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("up", "ArrowUp"),
        ("Arrow Down", "ArrowDown"),
        ("LEFT", "ArrowLeft"),
        ("arrowright", "ArrowRight"),
        ("spacebar", " "),
        ("return", "Enter"),
        ("esc", "Escape"),
        ("A", "a"),
        ("z", "z"),
    ],
)
def test_normalize_web_key_accepts_only_canonical_whitelist(value, expected):
    assert normalize_web_key(value) == expected


@pytest.mark.parametrize("value", ["", "ctrl+a", "Tab", "F1", "ä", "Enter;alert(1)"])
def test_normalize_web_key_rejects_unlisted_keys(value):
    with pytest.raises(ValueError, match="Unsupported key|must not be empty"):
        normalize_web_key(value)


def test_normalize_web_key_rejects_non_text():
    with pytest.raises(TypeError, match="Key must be text"):
        normalize_web_key(None)


def test_keyboard_payload_has_expected_browser_key_fields():
    assert keyboard_event_payload("ArrowUp") == {
        "key": "ArrowUp",
        "code": "ArrowUp",
        "keyCode": 38,
    }
    assert keyboard_event_payload("a") == {
        "key": "a",
        "code": "KeyA",
        "keyCode": 65,
    }


def _script_payload(script):
    match = re.search(r"const params = (.*);\n", script)
    assert match is not None
    return json.loads(match.group(1))


def test_keyboard_script_dispatches_bubbling_down_and_up_events():
    script = build_keyboard_event_script("space")
    assert _script_payload(script) == {
        "key": " ",
        "code": "Space",
        "keyCode": 32,
    }
    assert '["keydown", "keyup"]' in script
    assert "bubbles: true" in script


def test_click_link_script_json_escapes_untrusted_text():
    link_text = "L'actualité \"today\"\n'); alert(1); // ☃"
    script = build_click_link_script(link_text)

    assert _script_payload(script) == {"text": normalize_link_text(link_text)}
    assert "matches[0].click()" in script
    assert 'reason: matches.length ? "ambiguous" : "not-found"' in script
    assert script.count("alert(1)") == 1


@pytest.mark.parametrize("value", ["", " \n ", "x" * 501])
def test_normalize_link_text_rejects_empty_or_oversized_input(value):
    with pytest.raises(ValueError):
        normalize_link_text(value)


def test_jarvis_ui_browser_interaction_requests_use_qt_signals():
    from ui import JarvisUI

    class SignalRecorder:
        def __init__(self):
            self.value = None

        def emit(self, value):
            self.value = value

    key_signal = SignalRecorder()
    click_signal = SignalRecorder()
    jarvis_ui = JarvisUI.__new__(JarvisUI)
    jarvis_ui._win = SimpleNamespace(
        _browser_key_sig=key_signal,
        _browser_click_sig=click_signal,
    )

    assert jarvis_ui.press_key_in_webview("up") == "ArrowUp"
    assert key_signal.value == "ArrowUp"
    assert jarvis_ui.click_link_in_webview("  Read \n more  ") == "Read more"
    assert click_signal.value == "Read more"


def test_browser_interaction_tools_are_declared_with_required_arguments():
    main_file = Path(__file__).resolve().parents[1] / "main.py"
    module = ast.parse(main_file.read_text(encoding="utf-8"))
    declarations_assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS"
            for target in node.targets
        )
    )
    declarations = ast.literal_eval(declarations_assignment.value)

    tools = {item["name"]: item for item in declarations}
    assert tools["press_key"]["parameters"]["required"] == ["key"]
    assert tools["click_link"]["parameters"]["required"] == ["link_text"]


def test_browser_key_fallback_uses_qtest_on_focused_webview(monkeypatch):
    from PyQt6.QtCore import Qt

    from ui import MainWindow

    calls = []

    class ViewRecorder:
        def setFocus(self):
            calls.append(("focus",))

    class SignalRecorder:
        def emit(self, message):
            calls.append(("log", message))

    monkeypatch.setattr(
        "ui.QTest.keyClick",
        lambda widget, key: calls.append(("key", widget, key)),
    )
    view = ViewRecorder()
    window = SimpleNamespace(_browser_view=view, _log_sig=SignalRecorder())

    MainWindow._browser_native_key_fallback(window, "ArrowUp")

    assert calls[0] == ("focus",)
    assert calls[1][0] == "key"
    assert calls[1][1] is view
    assert calls[1][2] == Qt.Key.Key_Up

    calls.clear()
    MainWindow._browser_native_key_fallback(window, "a")
    assert calls[1][2] == Qt.Key.Key_A


def test_browser_key_dispatch_failure_uses_qt_fallback():
    from ui import MainWindow

    callbacks = []
    logs = []
    browser_panel = object()

    class StackRecorder:
        def currentWidget(self):
            return browser_panel

    class ViewRecorder:
        def setFocus(self):
            pass

    class PageRecorder:
        def runJavaScript(self, script, callback):
            callbacks.append(callback)

    window = SimpleNamespace(
        _main_content_stack=StackRecorder(),
        _browser_panel=browser_panel,
        _browser_view=ViewRecorder(),
        _browser_page=PageRecorder(),
        _log_sig=SimpleNamespace(emit=logs.append),
        _browser_key_dispatch_finished=lambda key, dispatched: (
            MainWindow._browser_key_dispatch_finished(window, key, dispatched)
        ),
        _browser_native_key_fallback=lambda key: callbacks.append(("fallback", key)),
    )

    MainWindow._press_key_in_webview(window, "ArrowUp")
    callbacks[0](False)

    assert callbacks[1] == ("fallback", "ArrowUp")
    assert any("uso fallback Qt" in entry for entry in logs)

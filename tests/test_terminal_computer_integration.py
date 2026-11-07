from __future__ import annotations

import threading

import pytest

from actions import (
    computer_input,
    computer_move,
    computer_task,
    terminal_exec,
    terminal_open_ext,
)
from core import actions_bridge, computer_use, confirm
from core.widget_registry import WidgetRegistry
from core.widgets_terminal_computer import register_widget_types


def test_widget_types_and_startup_event_queue():
    registry = WidgetRegistry()
    assert register_widget_types(registry) == {"terminal": True}
    assert set(registry.registered_types()) == {"terminal"}

    actions_bridge.clear()
    actions_bridge.push_event("terminal", {"event": "output", "stdout": "queued"})

    class FakeUI:
        def __init__(self):
            self.events = []

        def update_widget(self, widget_id, payload):
            self.events.append((widget_id, payload))

    ui = FakeUI()
    actions_bridge.set_ui(ui)
    assert ui.events == [("terminal", {"event": "output", "stdout": "queued"})]
    actions_bridge.clear()


def test_terminal_computer_plugin_mounts_widgets_and_handlers():
    from core.plugin_terminal_computer import install

    class FakeUI:
        def __init__(self):
            self.specs = []
            self.events = []
            self.removed_widgets = []

        def show_widget(self, *args, **kwargs):
            self.specs.append((args, kwargs))

        def update_widget(self, widget_id, payload):
            self.events.append((widget_id, payload))

        def remove_widget(self, widget_id):
            self.removed_widgets.append(widget_id)

    actions_bridge.clear()
    ui = FakeUI()
    actions_bridge.set_ui(ui)
    install(ui)
    assert [entry[0][1] for entry in ui.specs] == ["terminal"]
    assert ui.removed_widgets == ["computer_use"]
    actions_bridge.dispatch("terminal", "clear")
    assert ui.events[-1] == ("terminal", {"event": "clear"})
    with pytest.raises(KeyError, match="computer_use.pause"):
        actions_bridge.dispatch("computer_use", "pause")
    actions_bridge.clear()


def test_terminal_exec_reports_output_and_deny_list(monkeypatch):
    events = []
    monkeypatch.setattr(terminal_exec, "_emit", lambda event, **payload: events.append((event, payload)))
    monkeypatch.setattr(terminal_exec, "_audit", lambda *_args, **_kwargs: None)

    result = terminal_exec.run({"command": "echo ciao"})
    assert result["ok"] is True
    assert result["stdout"].strip() == "ciao"
    assert any(event == "output" and payload["stdout"].strip() == "ciao" for event, payload in events)

    blocked = terminal_exec.run({"command": "rm -rf /"})
    assert blocked["error"] == "blocked"
    assert events[-1][0] == "blocked"

    pending = terminal_exec.run({"command": "mv report.txt archive.txt"})
    assert pending["error"] == "confirmation_unavailable"
    assert not pending.get("pending")


def test_computer_loop_flag_is_off_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_COMPUTER_LOOP", raising=False)
    result = computer_task.run({"goal": "open a page"})
    assert result["error"] == "computer_loop_disabled"


def test_terminal_open_ext_preserves_cwd_behind_confirmation(monkeypatch):
    opened = []
    audited = []

    class FakeAuditLog:
        def __init__(self, _path):
            pass

        def record(self, **entry):
            audited.append(entry)

    monkeypatch.setattr(terminal_open_ext, "open_terminal", lambda params: opened.append(params) or "Opened terminal")
    monkeypatch.setattr(terminal_open_ext, "AuditLog", FakeAuditLog)
    monkeypatch.setattr(confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        confirm,
        "request",
        lambda _key, _title, _detail, run, **_kwargs: (
            run(),
            "[CONFIRMATION_PENDING] test confirmation",
        )[1],
    )

    result = terminal_open_ext.run({"cwd": "C:\\work"})
    assert result["pending"] is True
    assert opened == [{"confirmed": True, "cwd": "C:\\work"}]
    assert audited[0]["tool"] == "terminal_open_ext"


def test_legacy_computer_input_uses_real_confirmation_gate(monkeypatch):
    calls = []
    monkeypatch.setattr(
        computer_input,
        "request_confirmed_input",
        lambda tool, parameters: calls.append((tool, parameters)) or {"pending": True},
    )
    result = computer_input.computer_input({"action": "press", "key": "enter"})
    assert '"pending": true' in result
    assert calls == [("computer_input", {"action": "press", "key": "enter"})]
    assert computer_input.TOOL["risk_class"] == "destructive"


def test_terminal_input_requires_separate_confirmations_for_text_and_enter(monkeypatch):
    executed = []
    completed = threading.Event()
    shown = []

    monkeypatch.setattr(computer_use, "arm_emergency_stop", lambda: None)
    monkeypatch.setattr(
        computer_use,
        "require_allowed_foreground",
        lambda: (42, "cmd.exe"),
    )
    monkeypatch.setattr(
        computer_use,
        "execute_input",
        lambda parameters: (
            executed.append(parameters),
            completed.set() if len(executed) == 2 else None,
            {"result": "input sent"},
        )[-1],
    )
    from core import computer_action_support

    monkeypatch.setattr(computer_action_support, "audit", lambda *_args, **_kwargs: None)
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None)
    try:
        typed = computer_input.computer_input({
            "action": "type_text",
            "text": "echo hello",
        })
        assert '"pending": true' in typed
        assert "echo hello" in shown[-1][1]
        confirm.resolve(True)

        submitted = computer_input.computer_input({
            "action": "press",
            "key": "enter",
        })
        assert '"pending": true' in submitted
        confirm.resolve(True)

        assert completed.wait(2)
        assert [parameters["action"] for parameters in executed] == [
            "type_text",
            "press",
        ]
        assert all(parameters["confirmed"] is True for parameters in executed)
        assert all(parameters["_expected_window"] == 42 for parameters in executed)
    finally:
        confirm.resolve(False)
        confirm.bind(None, None)


def test_computer_move_requires_hud_confirmation(monkeypatch):
    from core import computer_action_support

    action_result = threading.Event()
    executed = []
    shown = []

    monkeypatch.setattr(computer_use, "validate_input_request", lambda _parameters: "move")
    monkeypatch.setattr(computer_use, "require_allowed_foreground", lambda: (5, "code.exe"))
    monkeypatch.setattr(computer_action_support, "audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        computer_use,
        "execute_input",
        lambda parameters: (executed.append(parameters), action_result.set(), {"result": "moved"})[-1],
    )
    confirm.bind(lambda title, detail: shown.append((title, detail)), lambda: None)
    try:
        result = computer_move.run({"x": 10, "y": 20})
        assert result["pending"] is True
        assert shown and executed == []
        confirm.resolve(True)
        assert action_result.wait(2)
        assert executed[0]["confirmed"] is True
        assert executed[0]["_expected_window"] == 5
    finally:
        confirm.resolve(False)
        confirm.bind(None, None)
        actions_bridge.clear()

from __future__ import annotations

import json

from actions import computer_read_screen
from core import computer_use


def test_read_screen_requires_confirmation_before_capture(monkeypatch):
    monkeypatch.setattr(
        computer_use,
        "capture_screen",
        lambda: (_ for _ in ()).throw(AssertionError("capture must not run")),
    )

    result = json.loads(computer_read_screen.read_screen({}))

    assert result == {"ok": False, "error": "explicit_confirmation_required"}


def test_read_screen_returns_bounded_local_ocr_without_persisting_text(monkeypatch):
    audit_entries = []
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: (7, "notepad.exe")
    )
    monkeypatch.setattr(
        computer_use,
        "capture_screen",
        lambda: (object(), {"left": 0, "top": 0}),
    )
    monkeypatch.setattr(
        computer_use,
        "ocr_screen",
        lambda **_kwargs: [{"text": "x" * 300} for _ in range(25)],
    )
    monkeypatch.setattr(
        "core.computer_action_support.audit",
        lambda *args: audit_entries.append(args),
    )

    result = json.loads(computer_read_screen.read_screen({"confirmed": True}))

    assert result["ok"] is True
    assert len(result["text"]) == 6000
    assert result["truncated"] is True
    assert result["word_count"] == 25
    assert audit_entries == [
        ("computer_read_screen", "completed", "process=notepad.exe; words=25")
    ]


def test_read_screen_discards_capture_if_foreground_changes(monkeypatch):
    foreground = iter(((7, "notepad.exe"), (8, "code.exe")))
    monkeypatch.setattr(computer_use, "emergency_stop_triggered", lambda: False)
    monkeypatch.setattr(
        computer_use, "require_allowed_foreground", lambda: next(foreground)
    )
    monkeypatch.setattr(
        computer_use,
        "capture_screen",
        lambda: (object(), {"left": 0, "top": 0}),
    )
    monkeypatch.setattr(
        computer_use,
        "ocr_screen",
        lambda **_kwargs: [{"text": "private text"}],
    )

    result = json.loads(computer_read_screen.read_screen({"confirmed": True}))

    assert result == {"ok": False, "error": "foreground_changed_during_capture"}

from __future__ import annotations

import pytest

from actions import computer_settings
from core import confirm


@pytest.mark.parametrize("action", ["close_app", "close_window"])
def test_closing_active_window_requires_confirmation(monkeypatch, action):
    executed = []
    pending = {}
    monkeypatch.setattr(computer_settings, "_PYAUTOGUI", True)
    monkeypatch.setitem(
        computer_settings.ACTION_MAP,
        action,
        lambda: executed.append(action),
    )
    monkeypatch.setattr(confirm, "pending_title", lambda: "")

    def request(*, key, title, detail, run):
        pending.update(key=key, title=title, detail=detail, run=run)
        return "[CONFIRMATION_PENDING] test"

    monkeypatch.setattr(confirm, "request", request)

    result = computer_settings.computer_settings({"action": action})

    assert "[CONFIRMATION_PENDING]" in result
    assert executed == []
    assert action in pending["key"]
    assert pending["title"]
    assert pending["detail"]
    pending["run"]()
    assert executed == [action]

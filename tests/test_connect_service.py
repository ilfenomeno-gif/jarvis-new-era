from __future__ import annotations

from types import SimpleNamespace

import pytest

from actions import connect_service


class _Connectors:
    def __init__(self, *, status="disconnected"):
        self._status = status
        self.cancelled = []

    def get(self, connector_id):
        if connector_id != "github":
            raise KeyError(connector_id)
        return SimpleNamespace(name="GitHub", id=connector_id)

    def status(self, _connector_id):
        return self._status

    def cancel_oauth(self, connector_id):
        self.cancelled.append(connector_id)


def test_connect_service_starts_oauth_before_opening_browser(monkeypatch):
    connectors = _Connectors()
    runtime = SimpleNamespace(connectors=connectors)
    calls = []

    def begin_oauth(connector_id):
        calls.append(("oauth", connector_id))
        return "https://github.com/login/oauth/authorize?client_id=test"

    opened = []
    monkeypatch.setattr(connect_service, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        connect_service.webbrowser,
        "open_new_tab",
        lambda url: opened.append(url) or calls.append(("browser", url)) or True,
    )
    player = SimpleNamespace(begin_connector_oauth=begin_oauth)

    result = connect_service.connect_service(
        {"connector_id": "github"},
        player=player,
    )

    assert calls == [
        ("oauth", "github"),
        (
            "browser",
            "https://github.com/login/oauth/authorize?client_id=test",
        ),
    ]
    assert opened == ["https://github.com/login/oauth/authorize?client_id=test"]
    assert "avviata" in result
    assert connectors.cancelled == []


def test_connect_service_cancels_pending_state_if_browser_does_not_open(monkeypatch):
    connectors = _Connectors()
    monkeypatch.setattr(
        connect_service,
        "get_runtime",
        lambda: SimpleNamespace(connectors=connectors),
    )
    monkeypatch.setattr(connect_service.webbrowser, "open_new_tab", lambda _url: False)
    player = SimpleNamespace(
        begin_connector_oauth=lambda _connector_id: "https://github.com/authorize"
    )

    with pytest.raises(RuntimeError, match="browser predefinito"):
        connect_service.connect_service({"connector_id": "github"}, player=player)
    assert connectors.cancelled == ["github"]


def test_connect_service_does_not_start_oauth_for_connected_service(monkeypatch):
    connectors = _Connectors(status="connected")
    monkeypatch.setattr(
        connect_service,
        "get_runtime",
        lambda: SimpleNamespace(connectors=connectors),
    )
    player = SimpleNamespace(
        begin_connector_oauth=lambda _connector_id: pytest.fail(
            "already-connected services must not start OAuth"
        )
    )

    assert connect_service.connect_service(
        {"connector_id": "github"}, player=player
    ) == "GitHub è già connesso."

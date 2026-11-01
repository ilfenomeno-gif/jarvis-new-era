"""Tests for opening code-server in JARVIS's browser."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins import vscode_web


def test_run_opens_code_server_in_internal_webview(monkeypatch):
    webview = Mock()
    browser = Mock()
    monkeypatch.setattr(vscode_web, "browser_control", browser)
    player = Mock(open_url_in_webview=webview)

    result = vscode_web.run({"action": "open"}, player=player)

    webview.assert_called_once_with("http://127.0.0.1:8080")
    browser.assert_not_called()
    assert "browser interno" in result


def test_run_falls_back_when_webview_method_is_missing(monkeypatch):
    browser = Mock(return_value="Opened in browser")
    monkeypatch.setattr(vscode_web, "browser_control", browser)
    player = Mock(spec=["write_log"])

    result = vscode_web.run({"action": "open"}, player=player)

    browser.assert_called_once_with(
        parameters={
            "action": "go_to",
            "url": "http://127.0.0.1:8080",
        },
        player=player,
    )
    player.write_log.assert_called_once()
    assert "browser esterno" in player.write_log.call_args.args[0]
    assert result == "Opened in browser"


def test_run_falls_back_and_logs_when_webview_raises(monkeypatch):
    webview = Mock(side_effect=RuntimeError("webview unavailable"))
    browser = Mock(return_value="Opened externally")
    monkeypatch.setattr(vscode_web, "browser_control", browser)
    player = Mock(open_url_in_webview=webview, write_log=Mock())

    result = vscode_web.run({"action": "open"}, player=player)

    webview.assert_called_once_with("http://127.0.0.1:8080")
    browser.assert_called_once_with(
        parameters={
            "action": "go_to",
            "url": "http://127.0.0.1:8080",
        },
        player=player,
    )
    player.write_log.assert_called_once()
    assert "webview unavailable" in player.write_log.call_args.args[0]
    assert result == "Opened externally"


def test_run_reports_browser_fallback_failure(monkeypatch):
    monkeypatch.setattr(
        vscode_web,
        "browser_control",
        Mock(side_effect=RuntimeError("browser unavailable")),
    )

    result = vscode_web.run({"action": "open"}, player=object())

    assert "Impossibile aprire code-server" in result
    assert "browser unavailable" in result


def test_run_rejects_unsupported_action_without_opening(monkeypatch):
    browser = Mock()
    monkeypatch.setattr(vscode_web, "browser_control", browser)
    player = Mock()

    result = vscode_web.run({"action": "close"}, player=player)

    assert "Azione non valida" in result
    browser.assert_not_called()
    player.open_url_in_webview.assert_not_called()


def test_tool_contract_is_discoverable_and_uses_run_handler():
    assert vscode_web.TOOL["name"] == vscode_web.PLUGIN["name"]
    assert vscode_web.TOOL["handler"] is vscode_web.run


def test_fallback_without_logger_does_not_prevent_browser_open(monkeypatch):
    browser = Mock(return_value="Opened externally")
    monkeypatch.setattr(vscode_web, "browser_control", browser)

    result = vscode_web.run({"action": "open"}, player=object())

    assert result == "Opened externally"
    browser.assert_called_once()


@pytest.mark.parametrize("parameters", [{}, {"action": "search"}])
def test_invalid_actions_are_rejected(parameters):
    assert "Azione non valida" in vscode_web.run(parameters)

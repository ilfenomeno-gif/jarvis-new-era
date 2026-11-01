"""Tests for the authenticated JARVIS WebSocket bridge without network I/O."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ws_server


class _FakeWebSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.close_call = None

    async def recv(self):
        if not self.incoming:
            raise RuntimeError("no auth message")
        return self.incoming.pop(0)

    def __aiter__(self):
        async def iterate():
            while self.incoming:
                yield self.incoming.pop(0)

        return iterate()

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def close(self, code=None, reason=None):
        self.close_call = {"code": code, "reason": reason}


class _FakeServer:
    def __init__(self):
        self.closed = asyncio.Event()
        self.close_calls = 0

    async def wait_closed(self):
        await self.closed.wait()

    def close(self):
        self.close_calls += 1
        self.closed.set()


@pytest.fixture
def log_path(monkeypatch, tmp_path):
    monkeypatch.setattr(ws_server, "_LOG_PATH", tmp_path / "logs" / "ws_server.log")
    monkeypatch.setattr(ws_server._LOGGER, "handlers", [])
    yield ws_server._LOG_PATH
    for handler in list(ws_server._LOGGER.handlers):
        handler.close()
        ws_server._LOGGER.removeHandler(handler)


def test_load_or_create_token_persists_and_preserves_existing_config(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "api_keys.json"
    config_path.write_text(
        json.dumps({"gemini_api_key": "placeholder-secret"}), encoding="utf-8"
    )
    monkeypatch.setattr(ws_server, "_CONFIG_PATH", config_path)

    token = ws_server._load_or_create_token()
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert token
    assert saved_config["ws_token"] == token
    assert saved_config["gemini_api_key"] == "placeholder-secret"
    assert ws_server._load_or_create_token() == token


@pytest.mark.parametrize(
    "first_message",
    [
        json.dumps({"type": "auth", "token": "wrong"}),
        json.dumps({"type": "ping"}),
        "{not-json",
        json.dumps(["not", "an", "object"]),
    ],
)
def test_auth_rejects_missing_invalid_or_malformed_credentials(first_message):
    websocket = _FakeWebSocket([first_message])

    asyncio.run(ws_server._handle_connection(websocket, "correct-token"))

    assert websocket.close_call is not None
    assert websocket.close_call["code"] == 4001


def test_auth_success_then_ping_returns_auth_status_and_pong():
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "correct-token"}),
            json.dumps({"type": "ping"}),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "correct-token"))

    assert websocket.sent == [
        {"type": "auth_ok"},
        {"type": "status", "state": "ready", "detail": "authenticated"},
        {"type": "pong"},
    ]
    assert websocket.close_call is None


def test_chat_dispatches_prompt_and_history_to_headless_gemini(monkeypatch):
    ask = Mock(return_value="Gemini answer")
    monkeypatch.setattr(ws_server, "ask_gemini", ask)
    history = [{"role": "user", "parts": [{"text": "Earlier"}]}]
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            json.dumps(
                {
                    "type": "chat",
                    "id": "chat-1",
                    "text": "Follow up",
                    "history": history,
                }
            ),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token"))

    ask.assert_called_once_with("Follow up", history)
    assert {"type": "reply", "id": "chat-1", "text": "Gemini answer"} in websocket.sent
    assert any(
        item.get("state") == "busy" for item in websocket.sent if item["type"] == "status"
    )
    assert websocket.sent[-1]["state"] == "ready"


def test_command_dispatches_through_plugin_registry():
    registry = Mock()
    registry.run.return_value = "Plugin result"
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            json.dumps(
                {
                    "type": "command",
                    "id": 8,
                    "name": "quick_notes",
                    "args": {"action": "list"},
                }
            ),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token", registry))

    registry.run.assert_called_once_with(
        "quick_notes",
        {"action": "list"},
        player=None,
        session_memory=None,
    )
    assert {"type": "reply", "id": 8, "text": "Plugin result"} in websocket.sent
    assert websocket.sent[-1]["state"] == "ready"


def test_invalid_json_after_auth_returns_error_status():
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            "{invalid",
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token"))

    assert websocket.sent[-1]["state"] == "error"


def test_invalid_chat_history_is_rejected_before_gemini_call(monkeypatch):
    ask = Mock()
    monkeypatch.setattr(ws_server, "ask_gemini", ask)
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            json.dumps(
                {
                    "type": "chat",
                    "id": "chat-2",
                    "text": "Question",
                    "history": [{"role": "system", "parts": [{"text": "bad"}]}],
                }
            ),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token"))

    ask.assert_not_called()
    assert websocket.sent[-1]["state"] == "error"


def test_internal_chat_error_sets_error_state_and_connection_continues(monkeypatch):
    monkeypatch.setattr(
        ws_server,
        "ask_gemini",
        Mock(side_effect=RuntimeError("Gemini unavailable")),
    )
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            json.dumps({"type": "chat", "id": "bad", "text": "Question"}),
            json.dumps({"type": "ping"}),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token"))

    assert any(
        item.get("state") == "error" and "Gemini unavailable" in item["detail"]
        for item in websocket.sent
        if item["type"] == "status"
    )
    assert websocket.sent[-1] == {"type": "pong"}


def test_command_without_registry_returns_error_status():
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth", "token": "token"}),
            json.dumps(
                {"type": "command", "id": "cmd", "name": "quick_notes", "args": {}}
            ),
        ]
    )

    asyncio.run(ws_server._handle_connection(websocket, "token"))

    assert websocket.sent[-1]["state"] == "error"
    assert websocket.sent[-1]["detail"] == "plugin registry is unavailable"


def test_start_server_uses_mocked_serve_and_stop_closes_it(
    monkeypatch, tmp_path, log_path
):
    fake_server = _FakeServer()

    async def fake_serve(*_args, **_kwargs):
        return fake_server

    serve = Mock(side_effect=fake_serve)
    monkeypatch.setattr(ws_server.websockets, "serve", serve)
    monkeypatch.setattr(ws_server, "_CONFIG_PATH", tmp_path / "api_keys.json")

    async def run_server():
        task = asyncio.create_task(ws_server.start_server())
        while not serve.called:
            await asyncio.sleep(0)
        serve.assert_called_once()
        assert serve.call_args.args[1:] == ("127.0.0.1", 8765)
        await ws_server.stop_server()
        await task

    asyncio.run(run_server())

    assert fake_server.close_calls == 1
    assert log_path.exists()


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "localhost"])
def test_start_server_rejects_non_loopback_or_non_ip_host(host):
    with pytest.raises(ValueError, match="loopback"):
        asyncio.run(ws_server.start_server(host=host))


def test_server_logging_uses_one_megabyte_rotation(log_path):
    ws_server._configure_logging()

    handlers = [
        handler
        for handler in ws_server._LOGGER.handlers
        if isinstance(handler, ws_server.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1_000_000

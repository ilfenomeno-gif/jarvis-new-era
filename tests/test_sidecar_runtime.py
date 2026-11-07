from __future__ import annotations

import json
import socketserver
import sys
import threading

import pytest

from core.sidecar_runtime import JsonRpcSidecar, SidecarError, run_optional_sidecar

TOKEN = "a" * 64


class _RpcHandler(socketserver.StreamRequestHandler):
    def handle(self):
        request = json.loads(self.rfile.readline().decode("utf-8"))
        params = request.get("params") or {}
        if params.get("token") != TOKEN:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32001, "message": "unauthorized"},
            }
        elif params.get("contractVersion") != 1:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32002, "message": "incompatible version"},
            }
        elif request.get("method") == "health":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"contractVersion": 1, "status": "ok", "implementation": "test"},
            }
        elif request.get("method") == "echo":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": params.get("value"),
            }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {"code": -32601, "message": "method not found"},
            }
        self.wfile.write(json.dumps(response).encode("utf-8") + b"\n")


class _RpcServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _SlowRpcHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.rfile.readline()
        threading.Event().wait(0.2)


def _server():
    server = _RpcServer(("127.0.0.1", 0), _RpcHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_sidecar_client_health_and_versioned_call():
    server, thread = _server()
    try:
        client = JsonRpcSidecar("127.0.0.1", server.server_address[1], TOKEN)
        assert client.health()["implementation"] == "test"
        assert client.call("echo", {"value": "from sidecar"}) == "from sidecar"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_disabled_sidecar_uses_python_fallback_without_connecting(monkeypatch):
    monkeypatch.setattr(
        "core.sidecar_runtime.socket.create_connection",
        lambda *_args, **_kwargs: pytest.fail("disabled feature must not connect"),
    )
    assert run_optional_sidecar(
        "rust", "echo", {"value": 4}, lambda: "python",
        environ={"JARVIS_POLYGLOT_RUST": "0"},
    ) == "python"


def test_enabled_sidecar_returns_call_result():
    server, thread = _server()
    try:
        result = run_optional_sidecar(
            "rust",
            "echo",
            {"value": 42},
            lambda: pytest.fail("healthy sidecar should handle the call"),
            environ={
                "JARVIS_POLYGLOT_RUST": "1",
                "JARVIS_POLYGLOT_RUST_PORT": str(server.server_address[1]),
                "JARVIS_POLYGLOT_TOKEN": TOKEN,
            },
        )
        assert result == 42
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_enabled_sidecar_failure_logs_and_falls_back():
    messages = []
    result = run_optional_sidecar(
        "dotnet",
        "echo",
        {},
        lambda: "python fallback",
        environ={
            "JARVIS_POLYGLOT_DOTNET": "1",
            "JARVIS_POLYGLOT_DOTNET_PORT": "65534",
            "JARVIS_POLYGLOT_TOKEN": TOKEN,
        },
        logger=messages.append,
        timeout_seconds=0.05,
    )
    assert result == "python fallback"
    assert len(messages) == 1 and "using Python fallback" in messages[0]


def test_sidecar_timeout_uses_python_fallback():
    server = _RpcServer(("127.0.0.1", 0), _SlowRpcHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    messages = []
    try:
        result = run_optional_sidecar(
            "rust",
            "echo",
            {},
            lambda: "timeout fallback",
            environ={
                "JARVIS_POLYGLOT_RUST": "1",
                "JARVIS_POLYGLOT_RUST_PORT": str(server.server_address[1]),
                "JARVIS_POLYGLOT_TOKEN": TOKEN,
            },
            logger=messages.append,
            timeout_seconds=0.05,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert result == "timeout fallback"
    assert len(messages) == 1 and "using Python fallback" in messages[0]


@pytest.mark.parametrize(
    ("program", "timeout"),
    [
        ("raise SystemExit(17)", 0.5),
        ("import time; time.sleep(30)", 0.05),
    ],
    ids=("binary-exits", "binary-does-not-respond"),
)
def test_binary_failure_uses_python_fallback(monkeypatch, program, timeout):
    monkeypatch.setattr(
        "core.sidecar_runtime._binary_command",
        lambda *_args: [sys.executable, "-c", program],
    )
    messages = []
    result = run_optional_sidecar(
        "rust",
        "health",
        None,
        lambda: "python fallback",
        environ={
            "JARVIS_POLYGLOT_RUST": "1",
            "JARVIS_POLYGLOT_RUST_BIN": sys.executable,
            "JARVIS_POLYGLOT_TOKEN": TOKEN,
        },
        logger=messages.append,
        timeout_seconds=timeout,
    )
    assert result == "python fallback"
    assert len(messages) == 1 and "using Python fallback" in messages[0]


def test_sidecar_client_rejects_non_loopback_hosts():
    with pytest.raises(SidecarError, match="loopback"):
        JsonRpcSidecar("example.com", 18761, TOKEN)

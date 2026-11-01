"""Tests for MCP transport/server, runtime actions and the voice transport."""

from __future__ import annotations

import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.action_loader import discover_actions
from core.jarvis_runtime import build_runtime
from core.mcp_server import McpServer, to_json_schema
from core.mcp_transport import HttpMcpInvoker, McpTransportError, stdio_invoker
from core.secret_store import SecretStore
from core.voice_transport import NullTransport

ROOT = Path(__file__).resolve().parents[1]


class _FakeBackend:
    def protect(self, data):
        return data[::-1]

    def unprotect(self, data):
        return data[::-1]


class _McpHandler(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((body.get("method"), self.headers.get("Authorization"),
                                self.headers.get("Mcp-Session-Id")))
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        if body["method"] == "initialize":
            result, extra = {"protocolVersion": "x"}, {"Mcp-Session-Id": "sess-1"}
        else:
            args = body["params"]["arguments"]
            result = {"content": [{"type": "text", "text": f"{body['params']['name']}:{args}"}]}
            extra = {}
        payload = ("data: " + json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
                   if body["method"] == "tools/call" else
                   json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}))
        kind = "text/event-stream" if body["method"] == "tools/call" else "application/json"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        for key, value in extra.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload.encode())


def test_http_invoker_handshake_bearer_and_sse():
    _McpHandler.seen = []
    server = HTTPServer(("127.0.0.1", 0), _McpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        invoke = HttpMcpInvoker(f"http://127.0.0.1:{server.server_port}/mcp", lambda: "tok")
        assert invoke("gmail.search", {"q": "x"}) == "search:{'q': 'x'}"
    finally:
        server.shutdown()
        server.server_close()

    assert [m for m, _, _ in _McpHandler.seen] == [
        "initialize", "notifications/initialized", "tools/call"]
    assert all(auth == "Bearer tok" for _, auth, _ in _McpHandler.seen)
    assert _McpHandler.seen[-1][2] == "sess-1"


def test_http_invoker_rejects_insecure_endpoint():
    with pytest.raises(McpTransportError):
        HttpMcpInvoker("http://example.com/mcp", lambda: None)


def test_stdio_invoker_uses_bare_tool_name():
    class Client:
        def call_tool(self, name, arguments):
            return {"content": [{"type": "text", "text": f"{name}!"}]}

    assert stdio_invoker(Client())("spotify.play", {}) == "play!"


def test_mcp_server_exposes_only_read_actions_by_default(tmp_path):
    registry = discover_actions(ROOT / "actions", logger=lambda _m: None)
    server = McpServer(registry)
    names = {t["name"] for t in server.tools()}

    assert "weather_report" in names and "send_message" not in names
    assert {t["name"] for t in McpServer(registry, allow_write=True).tools()} >= {"send_message"}

    out = io.StringIO()
    server.serve(io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"send_message"}}\n'
        'not json\n'), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[0]["result"]["serverInfo"]["name"] == "jarvis"
    assert replies[1]["error"]["code"] == -32602
    assert replies[2]["error"]["code"] == -32700


def test_json_schema_lowercases_types():
    assert to_json_schema({"type": "OBJECT", "properties": {"a": {"type": "STRING"}}}) == {
        "type": "object", "properties": {"a": {"type": "string"}}}


def test_runtime_actions_end_to_end(tmp_path):
    secrets = SecretStore(tmp_path / "config" / "secrets.json", _FakeBackend())
    runtime = build_runtime(base=_clone_base(tmp_path), secrets=secrets)

    runtime.skills.approve("google-workspace-briefing", reviewer="test")
    runtime.connectors.authenticate("google-workspace", "tok")
    runtime.connectors.grant("google-workspace", ["gmail.read", "calendar.read", "drive.read"])
    runtime.connectors.set_invoker("google-workspace", lambda tool, args: f"{tool} ok")

    route, activation = runtime.router.prepare("cosa ho oggi?")
    assert activation.ready
    assert runtime.connectors.call_tool("gmail.search", {}, skill=route.skill) == "gmail.search ok"
    runtime.connectors.revoke("google-workspace")
    assert runtime.skills.get("google-workspace-briefing").status == "review_required"
    assert any(e["tool"] == "connector.revoke" for e in runtime.audit.entries())


def _clone_base(tmp_path):
    import shutil
    base = tmp_path / "base"
    shutil.copytree(ROOT / "connectors", base / "connectors")
    shutil.copytree(ROOT / "skills", base / "skills")
    return base


def test_registry_cli_lifecycle(tmp_path):
    from core.registry_cli import run

    secrets = SecretStore(tmp_path / "config" / "secrets.json", _FakeBackend())
    runtime = build_runtime(base=_clone_base(tmp_path), secrets=secrets)

    assert run(["connect", "github"], runtime, read_token=lambda _p: "tok") == "github: connected"
    assert "error" in run(["grant", "github", "nope"], runtime)
    assert run(["grant", "github", "repo.read"], runtime).endswith("repo.read")
    assert json.loads(run(["skill-diff", "google-workspace-briefing"], runtime))["added_tools"]
    assert run(["skill-approve", "google-workspace-briefing", "--reviewer", "me"], runtime).endswith("me")
    assert "revoked" in run(["revoke", "github"], runtime)
    assert "tok" not in (tmp_path / "config" / "secrets.json").read_text(encoding="utf-8")


def test_null_voice_transport():
    transport = NullTransport()
    heard = []
    transport.on_transcript(heard.append)
    transport.feed("ciao")
    transport.speak("salve")

    assert heard == ["ciao"] and transport.spoken == ["salve"]

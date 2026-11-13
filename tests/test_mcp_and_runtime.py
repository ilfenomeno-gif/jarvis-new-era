"""Tests for MCP transport/server, runtime actions and the voice transport."""

from __future__ import annotations

import io
import json
import logging
import os
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
from core.spotify_transport import SpotifyApiInvoker
from core.voice_transport import NullTransport

ROOT = Path(__file__).resolve().parents[1]


class _FakeBackend:
    def protect(self, data):
        return data[::-1]

    def unprotect(self, data):
        return data[::-1]


class _McpHandler(BaseHTTPRequestHandler):
    seen: list = []
    seen_arguments: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append((body.get("method"), self.headers.get("Authorization"),
                                self.headers.get("Mcp-Session-Id"),
                                self.headers.get("MCP-Protocol-Version")))
        if body.get("method") == "tools/call":
            type(self).seen_arguments.append(
                (body["params"]["name"], body["params"]["arguments"])
            )
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
    _McpHandler.seen_arguments = []
    server = HTTPServer(("127.0.0.1", 0), _McpHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        invoke = HttpMcpInvoker(
            f"http://127.0.0.1:{server.server_port}/mcp",
            lambda: "tok",
            tool_map={"github.search_repositories": "search_repositories"},
        )
        assert invoke(
            "github.search_repositories",
            {"query": "python"},
        ) == "search_repositories:{'query': 'python'}"
    finally:
        server.shutdown()
        server.server_close()

    assert [entry[0] for entry in _McpHandler.seen] == [
        "initialize", "notifications/initialized", "tools/call"]
    assert all(auth == "Bearer tok" for _, auth, _, _ in _McpHandler.seen)
    assert _McpHandler.seen[-1][2] == "sess-1"
    assert _McpHandler.seen[0][3] is None
    assert all(version == "2025-03-26" for _, _, _, version in _McpHandler.seen[1:])
    assert _McpHandler.seen[-1][1].startswith("Bearer ")
    assert _McpHandler.seen[-1][1].endswith("tok")
    assert _McpHandler.seen_arguments == [
        ("search_repositories", {"query": "python"})
    ]


def test_http_invoker_reports_http_error_details_without_leaking_token():
    class Response:
        status_code = 422
        text = '{"error":"invalid query","token":"fake-secret"}'
        headers = {}

        def close(self):
            pass

    class Session:
        def post(self, *_args, **_kwargs):
            return Response()

    invoke = HttpMcpInvoker(
        "https://api.githubcopilot.com/mcp/",
        lambda: "fake-secret",
        session=Session(),
    )

    with pytest.raises(McpTransportError) as error:
        invoke("github.search_repositories", {"query": "python"})

    assert "HTTP 422" in str(error.value)
    assert "invalid query" in str(error.value)
    assert "fake-secret" not in str(error.value)


def test_http_invoker_decodes_multiline_sse_json_event():
    class Response:
        headers = {"Content-Type": "text/event-stream"}
        lines = (
            "event: message\n"
            "data: {\n"
            'data:   "jsonrpc": "2.0",\n'
            'data:   "result": {"ok": true}\n'
            "data: }"
        )

        def iter_lines(self, decode_unicode=False):
            return iter(self.lines.splitlines())

    assert HttpMcpInvoker._decode(Response()) == {
        "jsonrpc": "2.0",
        "result": {"ok": True},
    }


def test_http_invoker_rejects_insecure_endpoint():
    with pytest.raises(McpTransportError):
        HttpMcpInvoker("http://example.com/mcp", lambda: None)


def test_stdio_invoker_uses_bare_tool_name():
    class Client:
        def call_tool(self, name, arguments):
            return {"content": [{"type": "text", "text": f"{name}!"}]}

    assert stdio_invoker(Client())("spotify.play", {}) == "play!"


def test_spotify_api_invoker_searches_and_plays_with_bearer_token():
    class Response:
        status_code = 200
        text = '{"is_playing":true}'

        def raise_for_status(self):
            pass

        def json(self):
            return {"tracks": {"items": [{"uri": "spotify:track:abc"}]}}

    class Session:
        def __init__(self):
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append(("GET", url, kwargs))
            return Response()

        def put(self, url, **kwargs):
            self.calls.append(("PUT", url, kwargs))
            return Response()

    session = Session()
    invoker = SpotifyApiInvoker(lambda: "access-token", session=session)

    assert invoker("spotify.play", {"query": "brano"}) == "Riproduzione Spotify avviata."
    assert [call[0] for call in session.calls] == ["GET", "PUT"]
    assert session.calls[0][2]["params"]["q"] == "brano"
    assert session.calls[1][2]["json"] == {"uris": ["spotify:track:abc"]}
    assert all(
        call[2]["headers"]["Authorization"] == "Bearer access-token"
        for call in session.calls
    )


def test_spotify_api_invoker_reports_no_current_playback():
    class Response:
        status_code = 204
        text = ""

        def raise_for_status(self):
            pass

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    invoker = SpotifyApiInvoker(lambda: "access-token", session=Session())
    assert invoker("spotify.currently_playing", {}) == (
        "Nessun brano è attualmente in riproduzione."
    )


def test_spotify_api_invoker_rejects_missing_auth_and_invalid_tools():
    invoker = SpotifyApiInvoker(lambda: None)
    with pytest.raises(RuntimeError, match="non è autenticato"):
        invoker("spotify.currently_playing", {})
    with pytest.raises(ValueError, match="non supportato"):
        SpotifyApiInvoker(lambda: "access-token")("spotify.unknown", {})


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
    assert "canva" in runtime.connectors._invokers
    assert "higgsfield" in runtime.connectors._invokers
    assert "spotify" in runtime.connectors._invokers
    assert "google-workspace" in runtime.connectors._invokers
    google = next(item for item in runtime.connectors.view() if item["id"] == "google-workspace")
    assert google["transport_configured"] is True
    assert runtime.connectors.get("canva").tool_map["canva.search_designs"] == (
        "search-designs"
    )

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


def test_runtime_restores_github_token_scopes_and_repository_action(tmp_path):
    import json

    base = _clone_base(tmp_path)
    config = base / "config"
    config.mkdir()
    (config / "connectors_state.json").write_text(
        json.dumps({"granted": {"github": ["repo.read"]}, "errors": {}}),
        encoding="utf-8",
    )
    secrets = SecretStore(config / "secrets.json", _FakeBackend())
    secrets.set("connector:github", "fake-github-pat")
    runtime = build_runtime(base=base, secrets=secrets)

    try:
        assert runtime.connectors.status("github") == "connected"
        assert runtime.connectors.scopes.granted("github") == {"repo.read"}
        assert runtime.connectors.access_token("github") == "fake-github-pat"
        assert runtime.connectors.tool_ready("github.search_repositories") == (
            True,
            "",
        )

        actions = discover_actions(
            ROOT / "actions",
            reserved_names=set(),
            logger=lambda _message: None,
        )
        assert actions.has("github_user_repositories")
        declaration = next(
            item
            for item in actions.get_tool_declarations()
            if item["name"] == "github_user_repositories"
        )
        assert declaration["parameters"] == {
            "type": "OBJECT",
            "properties": {},
        }
    finally:
        runtime.watchdog.stop()
        runtime.public_apis.stop()


def test_runtime_loads_local_env_before_reading_connector_configuration(
    tmp_path, monkeypatch
):
    base = _clone_base(tmp_path)
    (base / ".env").write_text(
        "JARVIS_GITHUB_CLIENT_ID=github-test-client\n"
        "JARVIS_GITHUB_CLIENT_SECRET=github-test-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_SECRET", raising=False)
    secrets = SecretStore(tmp_path / "env-profile" / "secrets.json", _FakeBackend())

    runtime = build_runtime(base=base, secrets=secrets)

    assert runtime.connectors.oauth_configured("github")
    assert runtime.connectors.get("github").client_id_env == "JARVIS_GITHUB_CLIENT_ID"


@pytest.mark.parametrize(
    ("file_value", "expected_log"),
    [("test-client.apps.googleusercontent.com", "SI"), ("", "NO")],
)
def test_runtime_loads_google_env_before_catalog_and_logs_presence(
    tmp_path, monkeypatch, caplog, file_value, expected_log
):
    from core.connectors import ConnectorRegistry

    base = _clone_base(tmp_path)
    (base / ".env").write_text(
        f"JARVIS_GOOGLE_CLIENT_ID={file_value}\n"
        "JARVIS_GOOGLE_CLIENT_SECRET=test-google-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_SECRET", raising=False)
    original_init = ConnectorRegistry.__init__
    original_load_catalog = ConnectorRegistry.load_catalog
    observed = []

    def check_environment_at_init(registry, *args, **kwargs):
        observed.append(("init", os.environ.get("JARVIS_GOOGLE_CLIENT_ID")))
        original_init(registry, *args, **kwargs)

    def check_environment_at_catalog_load(registry, catalog_path):
        observed.append(("catalog", os.environ.get("JARVIS_GOOGLE_CLIENT_ID")))
        return original_load_catalog(registry, catalog_path)

    monkeypatch.setattr(ConnectorRegistry, "__init__", check_environment_at_init)
    monkeypatch.setattr(ConnectorRegistry, "load_catalog", check_environment_at_catalog_load)
    caplog.set_level(logging.INFO, logger="core.jarvis_runtime")
    secrets = SecretStore(tmp_path / "secrets.json", _FakeBackend())
    secrets.set("connector:google-workspace:client_id", "stale-vault-id")
    runtime = build_runtime(base=base, secrets=secrets)
    try:
        assert observed == [("init", file_value), ("catalog", file_value)]
        assert runtime.connectors.get("google-workspace").client_id_env == (
            "JARVIS_GOOGLE_CLIENT_ID"
        )
        google = next(
            item for item in runtime.connectors.view() if item["id"] == "google-workspace"
        )
        assert google["oauth_client_id"] == (file_value or "stale-vault-id")
        assert f"Google Client ID letto: {expected_log}" in caplog.text
        assert f"Trovato: {expected_log}" in caplog.text
        if file_value:
            assert f"Lunghezza: {len(file_value)} caratteri" in caplog.text
            assert f"Primi caratteri: {file_value[:10]}..." in caplog.text
        assert "test-client.apps.googleusercontent.com" not in caplog.text
        assert "test-google-secret" not in caplog.text
        assert "stale-vault-id" not in caplog.text
    finally:
        runtime.watchdog.stop()
        runtime.public_apis.stop()


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

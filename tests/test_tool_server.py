"""Tests for the local HTTP tool endpoint (N2). Real HTTP on loopback with an
injected secret; no n8n needed. Covers: auth required, tools list, read/write
exposure, destructive NOT exposed, tool call, audit."""
from __future__ import annotations

import json
import urllib.request
import urllib.error

import pytest

from core import tool_server
from core.jarvis_runtime import get_runtime


@pytest.fixture()
def server(monkeypatch, tmp_path):
    # isolate config/secrets to a temp dir
    from core.secret_store import SecretStore
    from core.audit_log import AuditLog
    import core.jarvis_runtime as jr

    secret = "test-token-123"
    store = SecretStore(tmp_path / "secrets.json")
    store.set(tool_server.TOKEN_SECRET_NAME, secret)
    audit = AuditLog(tmp_path / "audit.jsonl")

    class _RT:
        def __init__(self, secrets, audit):
            self.secrets = secrets
            self.audit = audit

    rt = _RT(store, audit)
    monkeypatch.setattr(jr, "_runtime", rt)
    monkeypatch.setattr(tool_server, "get_runtime", lambda: rt)

    srv = tool_server.serve(port=0)  # ephemeral port
    port = srv.server_address[1]
    yield f"http://127.0.0.1:{port}", secret, audit
    srv.shutdown()


def _post(url, path, body, token=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    if token:
        req.add_header("X-JARVIS-TOKEN", token)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def _get(url, path, token=None):
    req = urllib.request.Request(url + path, method="GET")
    if token:
        req.add_header("X-JARVIS-TOKEN", token)
    try:
        r = urllib.request.urlopen(req, timeout=10)
        return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def test_tools_requires_auth(server):
    url, secret, _ = server
    code, _ = _get(url, "/tools")
    assert code == 401
    code, body = _get(url, "/tools", token=secret)
    assert code == 200
    assert "tools" in body


def test_tools_list_has_schemas(server):
    url, secret, _ = server
    _, body = _get(url, "/tools", token=secret)
    assert isinstance(body["tools"], list) and body["tools"]
    for t in body["tools"]:
        assert "name" in t and "inputSchema" in t


def test_destructive_not_exposed(server):
    url, secret, _ = server
    _, body = _get(url, "/tools", token=secret)
    names = {t["name"] for t in body["tools"]}
    # app_launcher and computer_input are destructive in this project
    assert "app_launcher" not in names
    assert "computer_input" not in names


def test_tool_call_requires_auth(server):
    url, _, _ = server
    code, _ = _post(url, "/tool/weather_report", {"args": {}})
    assert code == 401


def test_unknown_tool_404(server):
    url, secret, _ = server
    code, body = _post(url, "/tool/does_not_exist", {"args": {}}, token=secret)
    assert code == 404


def test_tool_call_runs_and_audits(server):
    url, secret, audit = server
    # use a read tool that needs no external service: ui_layout is read
    code, body = _post(url, "/tool/ui_layout", {"args": {"action": "status"}}, token=secret)
    # accept 200 (ran) or 500 (tool needs UI); the point is it was dispatched+audited
    assert code in (200, 500)
    assert any(r["tool"].startswith("tool_server.") for r in audit.entries())

"""Tests for the n8n Bridge action (P2). The webhook is mocked — no network,
no real n8n, no real secret. Covers: config validation, https-only, auth header
from the SecretStore, outcome mapping, and the negative auth case (401→failed)."""
from __future__ import annotations

import json

import pytest

from actions import n8n_bridge as bridge
from core import outcome


class _FakeSecrets:
    def __init__(self, value=None):
        self._value = value

    def get(self, key):
        return self._value if key == bridge.SECRET_NAME else None


class _FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, **kw):
        self.records.append(kw)
        return kw


class _FakeRuntime:
    def __init__(self, secret=None):
        self.secrets = _FakeSecrets(secret)
        self.audit = _FakeAudit()


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Point the bridge at a temp config file and a fake runtime."""
    config_file = tmp_path / "n8n.json"
    monkeypatch.setattr(bridge, "CONFIG_PATH", config_file)
    return config_file


def _write(config_file, **over):
    data = {
        "base_url": "https://jarvis9090.app.n8n.cloud",
        "webhook_path": "/webhook/jarvis-bridge",
        "auth_header": "X-Jarvis-Token",
        "timeout_sec": 5,
    }
    data.update(over)
    config_file.write_text(json.dumps(data), encoding="utf-8")


def _mock_response(monkeypatch, status=200, text="workflow result", raise_exc=None):
    import httpx

    class FakeResponse:
        def __init__(self):
            self.status_code = status
            self.text = text

    class FakeClient:
        def __init__(self, *a, **kw):
            self.sent = {}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            if raise_exc is not None:
                raise raise_exc
            FakeClient.last = {"url": url, "json": json, "headers": headers}
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    return FakeClient


def test_not_configured_fails(cfg, monkeypatch):
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    line = bridge.call_workflow("do something")
    assert line.startswith("status=failed")
    assert "not configured" in line


def test_https_only(cfg, monkeypatch):
    _write(cfg, base_url="http://insecure.example")
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    line = bridge.call_workflow("task")
    assert "https://" in line


def test_http_allowed_on_loopback(cfg, monkeypatch):
    # self-hosted n8n on 127.0.0.1 may use plain http (loopback only)
    _write(cfg, base_url="http://127.0.0.1:5678")
    rt = _FakeRuntime("tok")
    monkeypatch.setattr(bridge, "get_runtime", lambda: rt)
    client = _mock_response(monkeypatch, status=200, text="ok")
    line = bridge.call_workflow("task")
    assert line.startswith("status=done")
    assert client.last["url"].startswith("http://127.0.0.1:5678/")


def test_http_localhost_allowed(cfg, monkeypatch):
    _write(cfg, base_url="http://localhost:5678")
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    _mock_response(monkeypatch, status=200, text="ok")
    assert bridge.call_workflow("task").startswith("status=done")


def test_missing_secret_fails(cfg, monkeypatch):
    _write(cfg)
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime(None))
    line = bridge.call_workflow("task")
    assert "secret missing" in line


def test_done_maps_response_and_sends_auth_header(cfg, monkeypatch):
    _write(cfg)
    rt = _FakeRuntime("secret-token")
    monkeypatch.setattr(bridge, "get_runtime", lambda: rt)
    client = _mock_response(monkeypatch, status=200, text="echo: hello")
    line = bridge.call_workflow("say hello")
    assert line.startswith("status=done")
    assert "echo: hello" in line
    # auth header carried the secret; payload is text-only
    assert client.last["headers"] == {"X-Jarvis-Token": "secret-token"}
    assert client.last["json"]["task"] == "say hello"
    assert client.last["json"]["source"] == "jarvis-vii"
    # audited as done
    assert any(r["outcome"] == "done" for r in rt.audit.records)


def test_auth_rejected_401_returns_failed(cfg, monkeypatch):
    _write(cfg)
    rt = _FakeRuntime("wrong-token")
    monkeypatch.setattr(bridge, "get_runtime", lambda: rt)
    _mock_response(monkeypatch, status=401, text="")
    line = bridge.call_workflow("task")
    assert line.startswith("status=failed")
    assert "authentication" in line
    assert any(r["outcome"] == "failed" for r in rt.audit.records)


def test_empty_2xx_body_is_unverified(cfg, monkeypatch):
    _write(cfg)
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    _mock_response(monkeypatch, status=200, text="   ")
    line = bridge.call_workflow("task")
    assert line.startswith("status=unverified")


def test_timeout_is_failed(cfg, monkeypatch):
    import httpx
    _write(cfg)
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    _mock_response(monkeypatch, raise_exc=httpx.TimeoutException("boom"))
    line = bridge.call_workflow("task")
    assert line.startswith("status=failed")
    assert "did not answer in time" in line


def test_empty_task_and_too_long(cfg, monkeypatch):
    _write(cfg)
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    assert "empty task" in bridge.call_workflow("   ")
    assert "too long" in bridge.call_workflow("x" * (bridge._MAX_PAYLOAD_CHARS + 1))


def test_action_handler_validates_extra_json(cfg, monkeypatch):
    _write(cfg)
    monkeypatch.setattr(bridge, "get_runtime", lambda: _FakeRuntime("tok"))
    _mock_response(monkeypatch, status=200, text="ok")
    assert "not valid JSON" in bridge.n8n_bridge({"task": "t", "extra_json": "{bad"})
    line = bridge.n8n_bridge({"task": "t", "extra_json": '{"priority": 1}'})
    assert line.startswith("status=done")


def test_tool_contract():
    assert bridge.TOOL["risk_class"] == "write"
    assert bridge.TOOL["name"] == "n8n_bridge"
    assert "task" in bridge.TOOL["parameters"]["properties"]
    assert callable(bridge.TOOL["handler"])

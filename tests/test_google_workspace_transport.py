from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from actions import connector_call
from core.audit_log import AuditLog
from core.connectors import ConnectorError, ConnectorRegistry
from core.google_workspace_transport import GoogleWorkspaceApiInvoker
from core.secret_store import SecretStore

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    def protect(self, data):
        return data[::-1]

    def unprotect(self, data):
        return data[::-1]


class Response:
    def __init__(self, status, data=None):
        self.status_code = status
        self.data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class Session:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def registry_with_session(tmp_path, session, monkeypatch):
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(ROOT / "connectors" / "catalog")
    registry.authenticate("google-workspace", "access-token")
    registry.grant("google-workspace", ["gmail.read"])
    registry.set_invoker(
        "google-workspace",
        GoogleWorkspaceApiInvoker(
            lambda: registry.access_token("google-workspace"),
            lambda: registry.access_token("google-workspace", force_refresh=True),
            session=session,
        ),
    )
    monkeypatch.setattr(connector_call, "get_runtime", lambda: SimpleNamespace(connectors=registry))
    return registry, secrets


def test_gmail_403_reaches_action_and_logs_http_error(tmp_path, monkeypatch, caplog):
    session = Session(Response(403))
    registry, _ = registry_with_session(tmp_path, session, monkeypatch)

    result = connector_call.connector_call({"tool": "gmail.search"})

    assert "Permesso Gmail mancante. Vai su Google Cloud e abilita l'API Gmail, poi riconnetti l'account." in result
    assert "Si è verificato un problema" not in result
    assert "HTTP 403 Forbidden" in caplog.text
    assert "access-token" not in caplog.text
    assert registry._audit.entries()[-1]["outcome"] == "error"


@pytest.mark.parametrize("data", [{}, {"messages": []}])
def test_gmail_empty_results_are_clean(tmp_path, monkeypatch, data):
    registry_with_session(tmp_path, Session(Response(200, data)), monkeypatch)
    assert connector_call.connector_call({"tool": "gmail.search"}) == "Nessuna email trovata."


def test_gmail_invalid_json_is_reported_as_error(tmp_path, monkeypatch):
    registry_with_session(tmp_path, Session(Response(200, ValueError("empty"))), monkeypatch)
    result = connector_call.connector_call({"tool": "gmail.search"})
    assert "JSON Gmail non valida o vuota" in result
    assert "Nessuna email" not in result


@pytest.mark.parametrize("status, phrase", [(401, "Unauthorized"), (429, "Too Many Requests")])
def test_gmail_http_errors_are_not_reported_as_empty(tmp_path, monkeypatch, caplog, status, phrase):
    session = Session(Response(status), Response(status))
    registry, secrets = registry_with_session(tmp_path, session, monkeypatch)
    if status == 401:
        registry.set_invoker(
            "google-workspace",
            GoogleWorkspaceApiInvoker(lambda: "access-token", lambda: "new-token", session=session),
        )
    result = connector_call.connector_call({"tool": "gmail.search"})
    assert f"HTTP {status} {phrase}" in result
    assert f"HTTP {status} {phrase}" in caplog.text
    assert "Nessuna email" not in result
    assert secrets.get("connector:google-workspace") == "access-token"


def test_gmail_403_on_message_details_is_propagated(tmp_path, monkeypatch):
    session = Session(Response(200, {"messages": [{"id": "abc"}]}), Response(403))
    registry_with_session(tmp_path, session, monkeypatch)
    result = connector_call.connector_call({"tool": "gmail.search"})
    assert "Permesso Gmail mancante." in result


def test_gmail_search_returns_sender_date_and_subject(tmp_path, monkeypatch):
    session = Session(
        Response(200, {"messages": [{"id": "abc"}]}),
        Response(200, {
            "internalDate": "1700000000000",
            "payload": {"headers": [
                {"name": "From", "value": "Alice <alice@example.test>"},
                {"name": "Date", "value": "Tue, 14 Nov 2023 22:13:20 +0000"},
                {"name": "Subject", "value": "Notizie"},
            ]},
        }),
    )
    registry_with_session(tmp_path, session, monkeypatch)
    result = connector_call.connector_call({
        "tool": "gmail.search",
        "arguments_json": json.dumps({"query": "-in:sent", "max_results": 1}),
    })
    message = json.loads(result)["messages"][0]
    assert message["from"] == "Alice <alice@example.test>"
    assert message["date"] == "Tue, 14 Nov 2023 22:13:20 +0000"
    assert message["subject"] == "Notizie"
    assert session.calls[0][1]["params"] == {"q": "-in:sent", "maxResults": 1}
    assert session.calls[1][1]["params"]["format"] == "metadata"


@pytest.mark.parametrize("force_by_401", [False, True])
def test_gmail_refreshes_token_before_or_after_401(tmp_path, monkeypatch, force_by_401):
    responses = [Response(401), Response(200, {})] if force_by_401 else [Response(200, {})]
    session = Session(*responses)
    registry, secrets = registry_with_session(tmp_path, session, monkeypatch)
    secrets.set("connector:google-workspace:refresh_token", "refresh-token")
    secrets.set("connector:google-workspace:client_id", "client-id")
    secrets.set("connector:google-workspace:client_secret", "client-secret")
    if not force_by_401:
        secrets.set("connector:google-workspace:expires_at", str(time.time() - 10))
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_SECRET", raising=False)
    token_requests = []

    class TokenResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"access_token":"new-token","expires_in":3600}'

    def refresh(request, timeout):
        token_requests.append(request)
        return TokenResponse()

    monkeypatch.setattr(urllib.request, "urlopen", refresh)
    assert connector_call.connector_call({"tool": "gmail.search"}) == "Nessuna email trovata."
    assert "refresh_token=refresh-token" in token_requests[0].data.decode("ascii")
    assert secrets.get("connector:google-workspace") == "new-token"
    assert session.calls[-1][1]["headers"]["Authorization"] == "Bearer new-token"
    assert registry.status("google-workspace") == "connected"


def test_expired_token_without_refresh_does_not_silently_use_expired_token(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl"))
    registry.load_catalog(ROOT / "connectors" / "catalog")
    registry.authenticate("google-workspace", "expired")
    secrets.set("connector:google-workspace:expires_at", str(time.time() - 1))
    with pytest.raises(ConnectorError, match="refresh token non disponibile"):
        registry.access_token("google-workspace")

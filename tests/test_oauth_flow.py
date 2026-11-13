from __future__ import annotations

import io
import json
import socket
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

import pytest

from core.audit_log import AuditLog
from core.connectors import ConnectorError, ConnectorRegistry
from core.secret_store import SecretStore


class FakeBackend:
    def protect(self, data: bytes) -> bytes:
        return b"enc:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[len(b"enc:"):][::-1]


class JsonResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps({"access_token": "oauth-access-token"}).encode("utf-8")


def _free_loopback_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_oauth_requires_a_registered_provider_client_id(
    tmp_path, monkeypatch
):
    from pathlib import Path

    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_SECRET", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")

    assert registry.oauth_configured("github") is False
    github = next(item for item in registry.view() if item["id"] == "github")
    assert github["oauth_redirect_uri"] == (
        "http://127.0.0.1:8770/oauth/github/callback"
    )
    assert github["oauth_setup"] == [
        "JARVIS_GITHUB_CLIENT_ID",
        "JARVIS_GITHUB_CLIENT_SECRET",
    ]
    assert github["transport_configured"] is True
    google = next(
        item for item in registry.view() if item["id"] == "google-workspace"
    )
    assert google["transport_configured"] is False
    canva = next(item for item in registry.view() if item["id"] == "canva")
    assert canva["transport_configured"] is True
    assert registry.get("canva").endpoint == "https://api.canva.com/connect/v1/mcp"
    assert canva["oauth_setup"] == [
        "JARVIS_CANVA_CLIENT_ID",
        "JARVIS_CANVA_CLIENT_SECRET",
    ]
    higgsfield = next(item for item in registry.view() if item["id"] == "higgsfield")
    assert higgsfield["transport_configured"] is True
    assert higgsfield["oauth_configured"] is True
    assert higgsfield["oauth_setup"] == []
    assert registry.get("higgsfield").authorize_url == (
        "https://clerk.higgsfield.ai/oauth/authorize"
    )
    spotify = next(item for item in registry.view() if item["id"] == "spotify")
    assert spotify["transport_configured"] is False
    with pytest.raises(ConnectorError, match="Client ID is missing"):
        registry.begin_oauth("github")


def test_ui_saved_oauth_credentials_start_pkce_and_survive_disconnect(
    tmp_path, monkeypatch
):
    from pathlib import Path

    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_CLIENT_SECRET", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    registry.get("github").redirect_uri = (
        f"http://127.0.0.1:{_free_loopback_port()}/oauth/github/callback"
    )
    registry.save_oauth_credentials("github", "test-client-id", "test-client-secret")
    monkeypatch.setenv("JARVIS_GITHUB_CLIENT_ID", "replacement-client-id")
    monkeypatch.setenv("JARVIS_GITHUB_CLIENT_SECRET", "replacement-client-secret")

    github = next(item for item in registry.view() if item["id"] == "github")
    assert github["oauth_configured"] is True
    assert github["oauth_setup"] == []
    assert github["oauth_client_id"] == "replacement-client-id"
    assert "test-client-secret" not in repr(github)

    authorization_url = registry.begin_oauth("github")
    authorization = parse_qs(urlsplit(authorization_url).query)
    assert authorization["client_id"] == ["replacement-client-id"]
    assert authorization["redirect_uri"] == [
        registry.get("github").redirect_uri
    ]
    assert authorization["code_challenge_method"] == ["S256"]
    assert "test-client-secret" not in authorization_url

    registry.authenticate("github", "test-access-token")
    registry.revoke("github")
    assert secrets.get("connector:github") is None
    assert secrets.get("connector:github:client_id") == "test-client-id"
    assert secrets.get("connector:github:client_secret") == "test-client-secret"


def test_google_credentials_start_oauth_without_an_mcp_endpoint(
    tmp_path, monkeypatch, capsys
):
    from core.env_config import load_env_file
    from core.oauth_flow import _build_authorization_url

    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_SECRET", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    descriptor = registry.get("google-workspace")
    assert descriptor.client_id_env == "JARVIS_GOOGLE_CLIENT_ID"
    assert descriptor.client_secret_env == "JARVIS_GOOGLE_CLIENT_SECRET"
    assert descriptor.redirect_uri == "http://127.0.0.1:8766/oauth/google/callback"
    assert descriptor.oauth_scopes == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/calendar",
    ]
    catalog_url = _build_authorization_url(
        descriptor, "test.apps.googleusercontent.com", "state", "challenge"
    )
    assert parse_qs(urlsplit(catalog_url).query)["redirect_uri"] == [
        "http://127.0.0.1:8766/oauth/google/callback"
    ]
    assert parse_qs(urlsplit(catalog_url).query)["scope"] == [
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/calendar"
    ]
    descriptor.redirect_uri = (
        f"http://127.0.0.1:{_free_loopback_port()}/oauth/google/callback"
    )
    before = next(item for item in registry.view() if item["id"] == descriptor.id)
    assert before["oauth_setup"] == [
        "JARVIS_GOOGLE_CLIENT_ID", "JARVIS_GOOGLE_CLIENT_SECRET"
    ]
    assert not before["transport_configured"]

    client_id = "google-id.apps.googleusercontent.com"
    registry.save_oauth_credentials(descriptor.id, client_id, "google-secret")
    after = next(item for item in registry.view() if item["id"] == descriptor.id)
    assert after["oauth_configured"]
    assert after["oauth_setup"] == []
    assert secrets.get("connector:google-workspace:client_secret") == "google-secret"
    assert "google-secret" not in (tmp_path / "secrets.json").read_text()

    client_id = "environment-id.apps.googleusercontent.com"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f'JARVIS_GOOGLE_CLIENT_ID="  {client_id}  "\n', encoding="utf-8"
    )
    load_env_file(env_file)
    authorization_url = registry.begin_oauth(descriptor.id)
    authorization = parse_qs(urlsplit(authorization_url).query)
    assert authorization["client_id"] == [client_id]
    assert authorization["code_challenge_method"] == ["S256"]
    assert authorization["redirect_uri"] == [descriptor.redirect_uri]
    assert "google-secret" not in authorization_url
    log = capsys.readouterr().out
    logged_url = log.split("URL autorizzazione Google: ", 1)[1].splitlines()[0]
    logged = parse_qs(urlsplit(logged_url).query)
    assert logged["client_id"] == [client_id]
    assert logged["redirect_uri"] == [descriptor.redirect_uri]
    assert logged["state"] == ["[REDACTED]"]
    assert authorization["state"][0] not in log
    assert "google-secret" not in log
    for key in authorization:
        if key != "state":
            assert logged[key] == authorization[key]

    callback = descriptor.redirect_uri + "?" + urlencode({
        "state": authorization["state"][0], "error": "access_denied"
    })
    with pytest.raises(HTTPError) as error:
        urlopen(callback, timeout=5)
    assert error.value.code == 400


@pytest.mark.parametrize("vault_id", [None, "", "stale-id"])
def test_google_env_credentials_override_stale_vault(tmp_path, monkeypatch, vault_id):
    from core.env_config import load_env_file

    env_file = tmp_path / ".env"
    env_file.write_text(
        "JARVIS_GOOGLE_CLIENT_ID=file-id.apps.googleusercontent.com\n"
        "JARVIS_GOOGLE_CLIENT_SECRET=file-secret\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_SECRET", raising=False)
    load_env_file(env_file)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    if vault_id is not None:
        secrets.set("connector:google-workspace:client_id", vault_id)
    secrets.set("connector:google-workspace:client_secret", "stale-secret")
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    descriptor = registry.get("google-workspace")
    assert registry._auth.oauth_credentials(descriptor) == (
        "file-id.apps.googleusercontent.com", "file-secret"
    )
    assert next(
        item for item in registry.view() if item["id"] == descriptor.id
    )["oauth_client_id"] == "file-id.apps.googleusercontent.com"


@pytest.mark.parametrize(
    ("client_id", "valid"),
    [
        ("  valid.apps.googleusercontent.com  ", True),
        ("  .apps.googleusercontent.com  ", False),
        ("valid .apps.googleusercontent.com", False),
        ("valid\u200b.apps.googleusercontent.com", False),
        ("  ", False),
        (None, False),
    ],
)
def test_google_client_id_validity_trims_outer_whitespace(client_id, valid):
    from core.oauth_flow import is_google_client_id_valid

    assert is_google_client_id_valid(client_id) is valid


def test_google_invalid_env_id_does_not_fall_back_to_valid_vault(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_ID", "wrong-id")
    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_SECRET", "test-secret")
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    secrets.set("connector:google-workspace:client_id", "vault.apps.googleusercontent.com")
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    with pytest.raises(ConnectorError, match="Client ID Google mancante o non valido"):
        registry.begin_oauth("google-workspace")


def test_authorization_url_redacts_oauth_secrets():
    from core.oauth_flow import _redacted_authorization_url

    redacted = _redacted_authorization_url(
        "https://provider.test/auth?client_id=id&client_secret=secret-value"
        "&STATE=state-value&redirect_uri=http%3A%2F%2F127.0.0.1"
    )
    assert redacted == (
        "https://provider.test/auth?client_id=[REDACTED]&client_secret=[REDACTED]"
        "&STATE=[REDACTED]&redirect_uri=http%3A%2F%2F127.0.0.1"
    )
    redacted_with_client = _redacted_authorization_url(
        "https://provider.test/auth?client_id=id&client_secret=secret-value"
        "&STATE=state-value&redirect_uri=http%3A%2F%2F127.0.0.1",
        show_client_id=True,
    )
    assert redacted_with_client == (
        "https://provider.test/auth?client_id=id&client_secret=[REDACTED]"
        "&STATE=[REDACTED]&redirect_uri=http%3A%2F%2F127.0.0.1"
    )


@pytest.mark.parametrize(
    "client_id", ["", "   ", "invalid-client-id", ".apps.googleusercontent.com"]
)
def test_google_invalid_client_id_fails_before_opening_browser(
    tmp_path, monkeypatch, caplog, client_id
):
    from actions import connect_service
    from core import oauth_flow

    monkeypatch.delenv("JARVIS_GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_SECRET", "test-secret")
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    if client_id:
        monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_ID", client_id)
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    monkeypatch.setattr(
        connect_service, "get_runtime", lambda: SimpleNamespace(connectors=registry)
    )
    monkeypatch.setattr(
        connect_service.webbrowser, "open_new_tab",
        lambda _url: pytest.fail("The browser must not open for an invalid Google ID"),
    )
    monkeypatch.setattr(
        oauth_flow, "ThreadingHTTPServer",
        lambda *_args, **_kwargs: pytest.fail("Invalid IDs must not start a listener"),
    )
    with pytest.raises(
        RuntimeError,
        match=r"Client ID Google mancante o non valido\. Controlla il file \.env\.",
    ):
        connect_service.connect_service({"connector_id": "google-workspace"})
    assert not next(
        item for item in registry.view() if item["id"] == "google-workspace"
    )["oauth_pending"]
    expected = "valore_non_valido" if client_id.strip() else "vuoto"
    assert f"Valore letto: {expected}" in caplog.text
    if client_id.strip():
        assert client_id not in caplog.text


def test_github_personal_access_token_is_saved_and_connects_without_oauth(
    tmp_path,
):
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    secrets.set("connector:github:refresh_token", "obsolete-refresh-token")
    secrets.set("connector:github:expires_at", "1")

    registry.save_personal_access_token("github", "  fake-github-pat  ")

    assert secrets.get("connector:github") == "fake-github-pat"
    assert secrets.get("connector:github:refresh_token") is None
    assert secrets.get("connector:github:expires_at") is None
    assert registry.access_token("github") == "fake-github-pat"
    assert registry.status("github") == "connected"
    assert registry.view()[0]["oauth_pending"] is False


def test_github_personal_access_token_rejects_empty_or_other_connector(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")

    with pytest.raises(ConnectorError, match="obbligatorio"):
        registry.save_personal_access_token("github", "  ")
    with pytest.raises(ConnectorError, match="only for GitHub"):
        registry.save_personal_access_token("spotify", "fake-token")


def test_github_authorization_url_uses_catalog_callback_and_client_id():
    from core.connectors import ConnectorDescriptor
    from core.oauth_flow import _build_authorization_url

    catalog = (
        Path(__file__).resolve().parents[1]
        / "connectors"
        / "catalog"
        / "github.json"
    )
    descriptor = ConnectorDescriptor.from_dict(
        json.loads(catalog.read_text(encoding="utf-8"))
    )
    authorization_url = _build_authorization_url(
        descriptor,
        "non-secret-test-client-id",
        "test-state",
        "test-challenge",
    )
    query = parse_qs(urlsplit(authorization_url).query)

    assert urlsplit(authorization_url).netloc == "github.com"
    assert query["client_id"] == ["non-secret-test-client-id"]
    assert query["redirect_uri"] == [
        "http://127.0.0.1:8770/oauth/github/callback"
    ]


def test_authorization_url_rejects_conflicting_callback_query_parameter():
    from core.connectors import ConnectorDescriptor
    from core.oauth_flow import OAuthFlowError, _build_authorization_url

    descriptor = ConnectorDescriptor(
        id="test-provider",
        name="Test Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url=(
            "https://provider.test/authorize?redirect_uri=https://evil.test/"
        ),
        token_url="https://provider.test/token",
        redirect_uri="http://127.0.0.1:12345/oauth/callback",
        oauth_scopes=["read"],
    )

    with pytest.raises(OAuthFlowError, match="does not exactly match"):
        _build_authorization_url(descriptor, "client-id", "state", "challenge")


def test_spotify_pkce_configuration_requires_only_client_id(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    registry.save_oauth_credentials("spotify", "spotify-client-id", "")

    spotify = next(item for item in registry.view() if item["id"] == "spotify")
    assert spotify["oauth_configured"] is True
    assert spotify["oauth_requires_client_secret"] is False
    assert spotify["oauth_redirect_uri"] == (
        "http://127.0.0.1:8768/oauth/spotify/callback"
    )


def test_oauth_dynamic_client_registration_and_refresh_token_storage(
    tmp_path, monkeypatch, caplog
):
    import logging

    from actions import connect_service
    from core import oauth_flow
    from core.connectors import ConnectorDescriptor

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="dynamic-provider",
        name="Dynamic Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://provider.test/authorize",
        token_url="https://provider.test/token",
        registration_url="https://provider.test/register",
        oauth_resource="https://provider.test/mcp",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/callback",
        oauth_scopes=["openid", "offline_access"],
    )
    descriptor.validate()
    calls = []

    class Response:
        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(self.value).encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        if request.full_url == descriptor.registration_url:
            return Response({"client_id": "registered-client"})
        return Response(
            {
                "access_token": "oauth-access-token",
                "refresh_token": "oauth-refresh-token",
                "expires_in": 3600,
            }
        )

    monkeypatch.setattr(oauth_flow, "urlopen", fake_urlopen)
    caplog.set_level(logging.INFO, logger="core.oauth_flow")
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.register(descriptor)

    def open_browser(url):
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
        opened_urls.append(url)
        return True

    opened_urls = []
    monkeypatch.setattr(
        connect_service,
        "get_runtime",
        lambda: SimpleNamespace(connectors=registry),
    )
    monkeypatch.setattr(
        connect_service.webbrowser,
        "open_new_tab",
        open_browser,
    )
    result = connect_service.connect_service(
        {"connector_id": descriptor.id},
        player=SimpleNamespace(begin_connector_oauth=registry.begin_oauth),
    )
    assert "avviata" in result
    authorization_url = opened_urls[0]
    authorization = parse_qs(urlsplit(authorization_url).query)
    assert next(
        item for item in registry.view() if item["id"] == descriptor.id
    )["oauth_pending"] is True
    assert (
        f"OAuth callback server listening on 127.0.0.1:{port}/oauth/callback"
        in caplog.text
    )

    registration_request = calls[0][0]
    registration_body = json.loads(registration_request.data)
    assert registration_body["redirect_uris"] == [descriptor.redirect_uri]
    assert authorization["resource"] == ["https://provider.test/mcp"]
    assert secrets.get("connector:dynamic-provider:client_id") == "registered-client"

    callback = (
        f"{descriptor.redirect_uri}?code=authorization-code"
        f"&state={authorization['state'][0]}"
    )
    wrong_callback = (
        f"http://127.0.0.1:{port}/oauth/not-github/callback"
        "?code=must-not-be-logged&state=must-not-be-logged"
    )
    with pytest.raises(HTTPError) as response:
        urlopen(wrong_callback, timeout=3)
    assert response.value.code == 404
    error_body = json.loads(response.value.read().decode("utf-8"))
    assert error_body == {
        "error": "Path non trovato",
        "received_path": "/oauth/not-github/callback",
        "expected_path": "/oauth/callback",
    }
    assert "must-not-be-logged" not in caplog.text

    with urlopen(callback, timeout=3) as response:
        assert response.status == 200

    assert next(
        item for item in registry.view() if item["id"] == descriptor.id
    )["oauth_pending"] is False
    assert secrets.get("connector:dynamic-provider") == "oauth-access-token"
    assert secrets.get("connector:dynamic-provider:refresh_token") == "oauth-refresh-token"
    assert secrets.get("connector:dynamic-provider:expires_at") is not None


def test_oauth_callback_server_crash_is_logged_and_reported(
    monkeypatch, caplog
):
    import logging
    import threading

    from core import oauth_flow
    from core.connectors import ConnectorDescriptor

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="crashing-provider",
        name="Crashing Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://provider.test/authorize",
        token_url="https://provider.test/token",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/callback",
        oauth_scopes=["openid"],
        client_id_env="JARVIS_TEST_CRASH_CLIENT_ID",
    )
    monkeypatch.setenv("JARVIS_TEST_CRASH_CLIENT_ID", "test-client")
    crash_reported = threading.Event()
    errors = []

    class Secrets:
        def get(self, _key):
            return None

        def set(self, _key, _value):
            pass

    class CrashingServer:
        def __init__(self, address, _handler):
            self.server_address = address
            self.daemon_threads = False

        def serve_forever(self):
            raise RuntimeError("simulated callback server crash")

        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(oauth_flow, "ThreadingHTTPServer", CrashingServer)
    caplog.set_level(logging.ERROR, logger="core.oauth_flow")

    def report_error(message):
        errors.append(message)
        crash_reported.set()

    authorization_url = oauth_flow.begin_loopback_oauth(
        descriptor,
        Secrets(),
        on_error=report_error,
    )

    assert urlsplit(authorization_url).scheme == "https"
    assert crash_reported.wait(2)
    assert "callback server crashed" in caplog.text
    assert errors == [
        "Il server callback OAuth si è arrestato in modo inatteso (RuntimeError)."
    ]


def test_oauth_callback_port_in_use_has_actionable_error(monkeypatch):
    import os

    from core import oauth_flow
    from core.connectors import ConnectorDescriptor
    from core.oauth_flow import OAuthFlowError, begin_loopback_oauth

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="github",
        name="GitHub",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/github/callback",
        oauth_scopes=["repo"],
        client_id_env="JARVIS_TEST_GITHUB_CLIENT_ID",
    )
    monkeypatch.setenv("JARVIS_TEST_GITHUB_CLIENT_ID", "github-test-client")

    class Secrets:
        def get(self, _key):
            return None

        def set(self, _key, _value):
            pass

    with socket.socket() as occupied_socket:
        occupied_socket.bind(("127.0.0.1", port))
        occupied_socket.listen()
        with pytest.raises(
            OAuthFlowError,
            match=f"port {port} is already in use on 127\\.0\\.0\\.1 by PID {os.getpid()}",
        ):
            begin_loopback_oauth(descriptor, Secrets())
        assert occupied_socket.fileno() >= 0
        assert oauth_flow._callback_port_state("127.0.0.1", port)[0] is not None


def test_oauth_callback_bind_retries_three_times(monkeypatch):
    from core import oauth_flow
    from core.connectors import ConnectorDescriptor
    from core.oauth_flow import OAuthFlowError

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="retry-provider",
        name="Retry Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://provider.test/authorize",
        token_url="https://provider.test/token",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/callback",
        oauth_scopes=["openid"],
        client_id_env="JARVIS_TEST_RETRY_CLIENT_ID",
    )
    monkeypatch.setenv("JARVIS_TEST_RETRY_CLIENT_ID", "test-client")
    monkeypatch.setattr(oauth_flow, "_callback_port_state", lambda *_args: (None, False))
    delays = []
    monkeypatch.setattr(oauth_flow.time, "sleep", delays.append)
    bind_attempts = []

    class Secrets:
        def get(self, _key):
            return None

        def set(self, _key, _value):
            pass

    class FailingServer:
        def __init__(self, _address, _handler):
            bind_attempts.append(True)
            raise OSError(10048, "address already in use")

    monkeypatch.setattr(oauth_flow, "ThreadingHTTPServer", FailingServer)

    with pytest.raises(OAuthFlowError, match="after 3 attempts"):
        oauth_flow.begin_loopback_oauth(descriptor, Secrets())

    assert len(bind_attempts) == 3
    assert delays == [oauth_flow._CALLBACK_BIND_RETRY_DELAY] * 2


def test_oauth_access_token_refreshes_expiring_credentials(tmp_path, monkeypatch):
    import time
    import urllib.request

    from core.connectors import ConnectorDescriptor, SecretStoreAuth

    descriptor = ConnectorDescriptor(
        id="refresh-provider",
        name="Refresh Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        token_url="https://provider.test/token",
        client_id_env="JARVIS_REFRESH_CLIENT_ID",
        redirect_uri="http://127.0.0.1:8760/oauth/callback",
        oauth_resource="https://provider.test/mcp",
    )
    monkeypatch.setenv("JARVIS_REFRESH_CLIENT_ID", "client-id")
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    secrets.set("connector:refresh-provider", "expired-access-token")
    secrets.set("connector:refresh-provider:refresh_token", "refresh-token")
    secrets.set("connector:refresh-provider:expires_at", str(time.time() - 10))
    requests = []

    class Response(JsonResponse):
        def read(self, _limit):
            return json.dumps(
                {"access_token": "new-access-token", "expires_in": 1800}
            ).encode("utf-8")

    def refresh(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", refresh)
    auth = SecretStoreAuth(secrets)

    assert auth.access_token(descriptor) == "new-access-token"
    assert secrets.get("connector:refresh-provider") == "new-access-token"
    assert float(secrets.get("connector:refresh-provider:expires_at")) > time.time()
    request, timeout = requests[0]
    assert timeout == 20
    assert "refresh_token=refresh-token" in request.data.decode("ascii")
    assert "resource=https%3A%2F%2Fprovider.test%2Fmcp" in request.data.decode("ascii")


def test_oauth_pkce_callback_exchanges_code_and_encrypts_access_token(
    tmp_path, monkeypatch
):
    from core import oauth_flow
    from core.connectors import ConnectorDescriptor

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="test-provider",
        name="Test Provider",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        scopes=["read"],
        authorize_url="https://provider.test/authorize",
        token_url="https://provider.test/token",
        client_id_env="JARVIS_TEST_OAUTH_CLIENT_ID",
        client_secret_env="JARVIS_TEST_OAUTH_CLIENT_SECRET",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/callback",
        oauth_scopes=["profile.read"],
        oauth_resource="https://provider.test/mcp",
        authorize_params={"prompt": "consent"},
    )
    descriptor.validate()
    monkeypatch.setenv("JARVIS_TEST_OAUTH_CLIENT_ID", "public-client-id")
    monkeypatch.setenv("JARVIS_TEST_OAUTH_CLIENT_SECRET", "test-client-secret")
    token_requests = []

    def exchange(request, timeout):
        token_requests.append((request, timeout))
        return JsonResponse()

    monkeypatch.setattr(oauth_flow, "urlopen", exchange)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    audit = AuditLog(tmp_path / "audit.jsonl")
    registry = ConnectorRegistry(tmp_path / "state.json", secrets, audit)
    registry.register(descriptor)
    authorization_url = registry.begin_oauth(descriptor.id)
    authorization = parse_qs(urlsplit(authorization_url).query)

    assert authorization["client_id"] == ["public-client-id"]
    assert authorization["response_type"] == ["code"]
    assert authorization["scope"] == ["profile.read"]
    assert authorization["code_challenge_method"] == ["S256"]
    assert authorization["resource"] == ["https://provider.test/mcp"]
    assert authorization["prompt"] == ["consent"]
    assert len(authorization["code_challenge"][0]) == 43

    callback = (
        f"{descriptor.redirect_uri}?code=authorization-code"
        f"&state={authorization['state'][0]}"
    )
    with urlopen(callback, timeout=3) as response:
        assert response.status == 200
        assert "Jarvis è connesso" in response.read().decode("utf-8")

    assert secrets.get("connector:test-provider") == "oauth-access-token"
    assert registry.status(descriptor.id) == "connected"
    assert audit.entries()[-1]["tool"] == "connector.authenticate"
    assert len(token_requests) == 1
    request, timeout = token_requests[0]
    assert request.full_url == descriptor.token_url
    assert timeout == 20
    body = parse_qs(request.data.decode("ascii"))
    assert body["client_id"] == ["public-client-id"]
    assert body["client_secret"] == ["test-client-secret"]
    assert body["code"] == ["authorization-code"]
    assert body["resource"] == ["https://provider.test/mcp"]
    assert body["code_verifier"]
    expected_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(body["code_verifier"][0].encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert authorization["code_challenge"] == [expected_challenge]


@pytest.mark.parametrize("error_source", ["callback", "token"])
def test_google_invalid_client_reports_provider_error_and_pkce(
    tmp_path, monkeypatch, error_source
):
    from core import oauth_flow

    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_ID", "test.apps.googleusercontent.com")
    monkeypatch.setenv("JARVIS_GOOGLE_CLIENT_SECRET", "test-google-secret")
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json", secrets, AuditLog(tmp_path / "audit.jsonl")
    )
    registry.load_catalog(Path(__file__).resolve().parents[1] / "connectors" / "catalog")
    descriptor = registry.get("google-workspace")
    descriptor.redirect_uri = (
        f"http://127.0.0.1:{_free_loopback_port()}/oauth/google/callback"
    )
    exchanges = []

    def reject_token_exchange(request, timeout):
        exchanges.append(parse_qs(request.data.decode("ascii")))
        raise HTTPError(
            descriptor.token_url, 401, "Unauthorized", {},
            io.BytesIO(
                b'{"error":"invalid_client",'
                b'"error_description":"The OAuth client was not found."}'
            ),
        )

    monkeypatch.setattr(oauth_flow, "urlopen", reject_token_exchange)
    auth = parse_qs(urlsplit(registry.begin_oauth(descriptor.id)).query)
    assert auth["code_challenge_method"] == ["S256"]
    assert auth["redirect_uri"] == [descriptor.redirect_uri]
    query = {"state": auth["state"][0]}
    if error_source == "callback":
        query.update(error="invalid_client", error_description="The OAuth client was not found.")
    else:
        query["code"] = "authorization-code"
    with pytest.raises(HTTPError) as response:
        urlopen(descriptor.redirect_uri + "?" + urlencode(query), timeout=3)
    assert response.value.code == (400 if error_source == "callback" else 401)
    google = next(item for item in registry.view() if item["id"] == descriptor.id)
    assert google["status"] == "error"
    assert "invalid_client" in google["oauth_error"]
    assert "Client OAuth non valido" in google["oauth_error"]
    assert "The OAuth client was not found." in google["oauth_error"]
    assert "test-google-secret" not in google["oauth_error"]
    if error_source == "token":
        verifier = exchanges[0]["code_verifier"][0]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert auth["code_challenge"] == [challenge]
        assert exchanges[0]["redirect_uri"] == [descriptor.redirect_uri]
    else:
        assert exchanges == []


def test_github_oauth_callback_reports_http_401_in_ui_state(
    tmp_path, monkeypatch
):
    from core import oauth_flow
    from core.connectors import ConnectorDescriptor

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="github",
        name="GitHub",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/github/callback",
        oauth_scopes=["repo"],
        client_id_env="JARVIS_TEST_GITHUB_CLIENT_ID",
        client_secret_env="JARVIS_TEST_GITHUB_CLIENT_SECRET",
    )
    descriptor.validate()
    monkeypatch.setenv("JARVIS_TEST_GITHUB_CLIENT_ID", "github-test-client")
    monkeypatch.setenv("JARVIS_TEST_GITHUB_CLIENT_SECRET", "github-test-secret")

    def reject_token_exchange(_request, timeout):
        assert timeout == 20
        raise HTTPError(
            "https://github.com/login/oauth/access_token",
            401,
            "Unauthorized",
            {},
            io.BytesIO(
                b'{"error":"incorrect_client_credentials",'
                b'"error_description":"The client_id and/or client_secret are '
                b'incorrect."}'
            ),
        )

    monkeypatch.setattr(oauth_flow, "urlopen", reject_token_exchange)
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    registry = ConnectorRegistry(
        tmp_path / "state.json",
        secrets,
        AuditLog(tmp_path / "audit.jsonl"),
    )
    registry.register(descriptor)
    authorization_url = registry.begin_oauth("github")
    authorization = parse_qs(urlsplit(authorization_url).query)

    callback = (
        f"{descriptor.redirect_uri}?code=authorization-code"
        f"&state={authorization['state'][0]}"
    )
    try:
        urlopen(callback, timeout=3)
    except HTTPError as response:
        assert response.code == 401
        response_text = response.read().decode("utf-8")
        assert "Credenziali OAuth non valide" in response_text
        assert "github-test-secret" not in response_text
    else:
        raise AssertionError("OAuth callback should return HTTP 401.")

    github = next(item for item in registry.view() if item["id"] == "github")
    assert github["status"] == "error"
    assert "Credenziali OAuth non valide" in github["oauth_error"]
    assert secrets.get("connector:github") is None


def test_oauth_provider_denial_is_reported_with_error_code(tmp_path, monkeypatch):
    from core.connectors import ConnectorDescriptor
    from core.oauth_flow import begin_loopback_oauth

    port = _free_loopback_port()
    descriptor = ConnectorDescriptor(
        id="github",
        name="GitHub",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        redirect_uri=f"http://127.0.0.1:{port}/oauth/github/callback",
        oauth_scopes=["repo"],
        client_id_env="JARVIS_TEST_DENIAL_CLIENT_ID",
    )
    monkeypatch.setenv("JARVIS_TEST_DENIAL_CLIENT_ID", "github-test-client")

    class Secrets:
        def get(self, _key):
            return None

        def set(self, _key, _value):
            pass

    errors = []
    authorization_url = begin_loopback_oauth(
        descriptor,
        Secrets(),
        on_error=errors.append,
    )
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]
    callback = (
        f"{descriptor.redirect_uri}?error=redirect_uri_mismatch"
        f"&error_description=Callback+URL+mismatch&state={state}"
    )
    try:
        urlopen(callback, timeout=3)
    except HTTPError as response:
        assert response.code == 400
        assert "redirect_uri_mismatch" in response.read().decode("utf-8")
    else:
        raise AssertionError("OAuth callback should return HTTP 400.")
    assert errors == [
        "redirect_uri_mismatch: l'URI di callback configurato nel provider "
        "non corrisponde a quello di Jarvis."
    ]


def test_github_credential_test_checks_api_reachability_without_claiming_secret_valid(
    monkeypatch,
):
    from core import oauth_flow
    from core.connectors import ConnectorDescriptor

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"verifiable_password_authentication":true}'

    requests = []

    def github_api(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(oauth_flow, "urlopen", github_api)
    descriptor = ConnectorDescriptor(
        id="github",
        name="GitHub",
        type="remote-mcp",
        transport="streamable-http",
        auth="oauth2",
        client_secret_env="JARVIS_GITHUB_CLIENT_SECRET",
    )

    message = oauth_flow.test_oauth_provider_connection(
        descriptor,
        "github-client-id",
        "github-client-secret",
    )
    assert "API GitHub raggiungibile" in message
    assert "verificato da GitHub durante il login" in message
    request, timeout = requests[0]
    assert request.full_url == "https://api.github.com/meta"
    assert timeout == 8
    assert request.data is None

"""Loopback OAuth 2.0 authorization-code flow with PKCE."""

from __future__ import annotations

import base64
import errno
import hashlib
import html
import json
import logging
import os
import secrets
import socket
import threading
import time
import unicodedata
from collections.abc import Callable
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class OAuthFlowError(RuntimeError):
    pass


GOOGLE_CLIENT_ID_ERROR = (
    "Client ID Google mancante o non valido. Controlla il file .env."
)


def is_google_client_id_valid(client_id: str | None) -> bool:
    suffix = ".apps.googleusercontent.com"
    client_id = client_id.strip() if isinstance(client_id, str) else ""
    return bool(
        client_id.endswith(suffix)
        and client_id != suffix
        and not any(
            char.isspace() or unicodedata.category(char) in {"Cc", "Cf"}
            for char in client_id
        )
    )


def _redacted_authorization_url(url: str, *, show_client_id: bool = False) -> str:
    parts = urlsplit(url)
    sensitive = {
        "state", "client_id", "client_secret", "client_assertion", "code", "code_verifier",
        "access_token", "refresh_token", "id_token",
    }
    if show_client_id:
        sensitive.remove("client_id")
    query = []
    for parameter in parts.query.split("&"):
        name, separator, value = parameter.partition("=")
        if unquote_plus(name).lower() in sensitive:
            value = "[REDACTED]"
        query.append(name + separator + value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(query), parts.fragment))


def _build_authorization_url(
    descriptor,
    client_id: str,
    state: str,
    challenge: str,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": descriptor.redirect_uri,
        "scope": " ".join(descriptor.oauth_scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    params.update(descriptor.authorize_params)
    if descriptor.oauth_resource:
        params["resource"] = descriptor.oauth_resource

    authorize = urlsplit(descriptor.authorize_url)
    query = urlencode(
        [*parse_qsl(authorize.query, keep_blank_values=True), *params.items()]
    )
    authorization_url = urlunsplit(
        (
            authorize.scheme,
            authorize.netloc,
            authorize.path,
            query,
            authorize.fragment,
        )
    )
    outgoing = parse_qs(urlsplit(authorization_url).query, keep_blank_values=True)
    if outgoing.get("client_id") != [client_id] or not client_id.strip():
        raise OAuthFlowError(
            f"{descriptor.name} authorization URL has a missing or invalid Client ID."
        )
    if outgoing.get("redirect_uri") != [descriptor.redirect_uri]:
        raise OAuthFlowError(
            f"{descriptor.name} authorization URL callback does not exactly match "
            "the connector's configured redirect URI."
        )
    return authorization_url


_CALLBACK_BIND_ATTEMPTS = 3
_CALLBACK_BIND_RETRY_DELAY = 1.0
_CALLBACK_TIME_WAIT_GRACE = 2.0


def _callback_port_state(host: str, port: int) -> tuple[str | None, bool]:
    try:
        import psutil
    except ImportError as exc:
        raise OAuthFlowError(
            "Cannot inspect OAuth callback port ownership: install psutil."
        ) from exc

    try:
        connections = psutil.net_connections(kind="inet")
    except (OSError, psutil.Error) as exc:
        raise OAuthFlowError(
            f"Cannot inspect OAuth callback port {port} ({type(exc).__name__})."
        ) from exc

    time_wait = False
    for connection in connections:
        local_address = connection.laddr
        if not local_address or local_address.port != port:
            continue
        is_listening = connection.status == psutil.CONN_LISTEN or (
            os.name == "nt"
            and connection.status == psutil.CONN_NONE
            and connection.type == socket.SOCK_STREAM
        )
        if is_listening:
            owner = f"PID {connection.pid}" if connection.pid is not None else "unknown process"
            if connection.pid is not None:
                try:
                    process = psutil.Process(connection.pid)
                    command = " ".join(process.cmdline()).lower()
                    if process.name().lower().startswith("python") and (
                        "jarvis-vii-app" in command and "main.py" in command
                    ):
                        owner = f"Jarvis Python process PID {connection.pid}"
                except (psutil.Error, OSError):
                    pass
            return owner, time_wait
        if connection.status == psutil.CONN_TIME_WAIT:
            time_wait = True
    return None, time_wait


def _wait_for_callback_time_wait(host: str, port: int) -> str | None:
    deadline = time.monotonic() + _CALLBACK_TIME_WAIT_GRACE
    while True:
        listener, time_wait = _callback_port_state(host, port)
        if listener or not time_wait or time.monotonic() >= deadline:
            return listener
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))


def _failure_details(
    descriptor,
    *,
    error_code: str = "",
    description: str = "",
    status: int | None = None,
) -> str:
    known_errors = {
        "redirect_uri_mismatch": (
            "redirect_uri_mismatch: l'URI di callback configurato nel provider "
            "non corrisponde a quello di Jarvis."
        ),
        "bad_verification_code": (
            "bad_verification_code: il codice OAuth è scaduto, è già stato usato "
            "o non corrisponde al Client ID."
        ),
        "incorrect_client_credentials": (
            "Credenziali OAuth non valide: verifica Client ID e Client Secret."
        ),
        "invalid_client": (
            "Client OAuth non valido: verifica Client ID e Client Secret."
        ),
        "access_denied": "Autorizzazione negata dall'utente o dal provider.",
    }
    if error_code in known_errors:
        if descriptor.id == "google-workspace":
            details = f"{error_code}: {known_errors[error_code]}"
            if description:
                details += f" Dettaglio del provider: {description[:300]}"
            return details
        return known_errors[error_code]

    if descriptor.id == "github" and status in {400, 401}:
        return (
            f"GitHub ha rifiutato il token OAuth (HTTP {status}). "
            "Verifica Client ID, Client Secret, callback URL e codice OAuth."
        )

    parts = []
    if error_code:
        parts.append(f"Errore OAuth {error_code}")
    elif status is not None:
        parts.append(f"Il provider ha rifiutato OAuth (HTTP {status})")
    else:
        parts.append("La richiesta OAuth non è riuscita")
    if description:
        parts.append(description[:300])
    return ": ".join(parts)


def test_oauth_provider_connection(
    descriptor,
    client_id: str,
    client_secret: str,
) -> str:
    """Check provider reachability and local credential completeness, not secret validity."""
    if not client_id.strip():
        raise OAuthFlowError("Inserisci il Client ID.")
    if descriptor.client_secret_env and not client_secret.strip():
        raise OAuthFlowError("Inserisci il Client Secret.")
    if descriptor.id != "github":
        raise OAuthFlowError(
            f"Verifica API non supportata per {descriptor.name}."
        )

    request = Request(
        "https://api.github.com/meta",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Jarvis-OAuth-setup",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=8) as response:
            if response.status != 200:
                raise OAuthFlowError(
                    f"GitHub API non disponibile (HTTP {response.status})."
                )
            json.loads(response.read(64_000).decode("utf-8"))
    except HTTPError as exc:
        raise OAuthFlowError(
            f"GitHub API ha restituito HTTP {exc.code}."
        ) from exc
    except (URLError, TimeoutError, HTTPException, OSError) as exc:
        raise OAuthFlowError(
            f"Impossibile raggiungere GitHub API ({type(exc).__name__})."
        ) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OAuthFlowError("GitHub API ha restituito una risposta non valida.") from exc

    return (
        "API GitHub raggiungibile. Il Client Secret verrà verificato da GitHub "
        "durante il login OAuth."
    )


def begin_loopback_oauth(
    descriptor,
    secret_store,
    *,
    on_token=None,
    on_error: Callable[[str], None] | None = None,
    timeout: float = 300,
) -> str:
    redirect = urlsplit(descriptor.redirect_uri)
    if (
        redirect.scheme != "http"
        or redirect.hostname not in {"127.0.0.1", "localhost"}
        or redirect.port is None
        or not redirect.path.startswith("/")
        or redirect.query
        or redirect.fragment
    ):
        raise OAuthFlowError("OAuth redirect must be an HTTP loopback URL with a port.")
    if not descriptor.authorize_url or not descriptor.token_url:
        raise OAuthFlowError(f"{descriptor.name} OAuth endpoints are not configured.")
    if not descriptor.oauth_scopes:
        raise OAuthFlowError(f"{descriptor.name} OAuth scopes are not configured.")

    key = f"connector:{descriptor.id}"
    client_id = (
        os.environ.get(descriptor.client_id_env, "").strip()
        if descriptor.client_id_env
        else ""
    ) or (secret_store.get(f"{key}:client_id") or "").strip()
    client_secret = (
        os.environ.get(descriptor.client_secret_env, "").strip()
        if descriptor.client_secret_env
        else ""
    ) or (secret_store.get(f"{key}:client_secret") or "")
    if descriptor.registration_url and not client_id:
        registration = Request(
            descriptor.registration_url,
            data=json.dumps(
                {
                    "client_name": "Jarvis",
                    "redirect_uris": [descriptor.redirect_uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                }
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(registration, timeout=20) as response:
                registration_data = json.loads(
                    response.read(64_000).decode("utf-8")
                )
        except Exception as exc:
            raise OAuthFlowError(
                f"{descriptor.name} OAuth client registration failed "
                f"({type(exc).__name__})."
            ) from exc
        client_id = registration_data.get("client_id", "")
        client_secret = registration_data.get("client_secret", "")
        if not isinstance(client_id, str) or not client_id:
            raise OAuthFlowError(
                f"{descriptor.name} registration did not return a client ID."
            )
        secret_store.set(f"{key}:client_id", client_id)
        if isinstance(client_secret, str) and client_secret:
            secret_store.set(f"{key}:client_secret", client_secret)
    if descriptor.id == "google-workspace" and not is_google_client_id_valid(client_id):
        logging.getLogger(__name__).error(
            "[ERROR] Validazione Google fallita. Valore letto: %s",
            "vuoto" if not client_id else "valore_non_valido",
        )
        raise OAuthFlowError(GOOGLE_CLIENT_ID_ERROR)
    if not client_id:
        setup = (
            " Add the credentials in Plugins & Connections"
            if descriptor.oauth_setup_url
            else ""
        )
        raise OAuthFlowError(f"{descriptor.name} Client ID is missing.{setup}")
    if descriptor.client_secret_env and not client_secret:
        raise OAuthFlowError(
            f"{descriptor.name} Client Secret is missing. Add the credentials "
            "in Plugins & Connections."
        )
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    authorization_url = _build_authorization_url(
        descriptor,
        client_id,
        state,
        challenge,
    )
    completed = threading.Event()
    logger = logging.getLogger(__name__)

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            query_keys = sorted(parse_qs(request.query).keys())
            print(
                f"Richiesta ricevuta sul percorso: {request.path}",
                flush=True,
            )
            logger.info(
                "OAuth callback request for connector %s: path=%s query_keys=%s",
                descriptor.id,
                request.path,
                query_keys,
            )
            if request.path != redirect.path:
                logger.warning(
                    "OAuth callback path mismatch for connector %s: "
                    "received=%s expected=%s",
                    descriptor.id,
                    request.path,
                    redirect.path,
                )
                self._respond_json(
                    404,
                    {
                        "error": "Path non trovato",
                        "received_path": request.path,
                        "expected_path": redirect.path,
                    },
                )
                return
            query = parse_qs(request.query)
            received_state = query.get("state", [""])[0]
            code = query.get("code", [""])[0]
            provider_error = query.get("error", [""])[0][:100]
            provider_description = query.get("error_description", [""])[0][:300]
            if (
                len(received_state) > 256
                or len(code) > 4096
                or not secrets.compare_digest(received_state, state)
            ):
                self._fail(
                    400,
                    "Autorizzazione non valida: il parametro state non corrisponde. "
                    "Riprova il login OAuth.",
                    error_code="invalid_state",
                )
                completed.set()
                return
            if provider_error:
                message = _failure_details(
                    descriptor,
                    error_code=provider_error,
                    description=provider_description,
                )
                self._fail(400, message, error_code=provider_error)
                completed.set()
                return
            if not code:
                self._fail(
                    400,
                    "Codice di autorizzazione mancante nella risposta del provider.",
                    error_code="missing_code",
                )
                completed.set()
                return
            try:
                body = {
                    "grant_type": "authorization_code",
                    "client_id": client_id,
                    "code": code,
                    "redirect_uri": descriptor.redirect_uri,
                    "code_verifier": verifier,
                }
                if descriptor.oauth_resource:
                    body["resource"] = descriptor.oauth_resource
                if client_secret:
                    body["client_secret"] = client_secret
                request = Request(
                    descriptor.token_url,
                    data=urlencode(body).encode("ascii"),
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    method="POST",
                )
                with urlopen(request, timeout=20) as response:
                    token_data = json.loads(response.read(64_000).decode("utf-8"))
                provider_code = token_data.get("error")
                if isinstance(provider_code, str) and provider_code:
                    provider_description = str(
                        token_data.get("error_description", "")
                    )[:300]
                    message = _failure_details(
                        descriptor,
                        error_code=provider_code[:100],
                        description=provider_description,
                    )
                    self._fail(
                        400,
                        message,
                        error_code=provider_code[:100],
                    )
                    return
                access_token = token_data.get("access_token")
                if not isinstance(access_token, str) or not access_token:
                    raise OAuthFlowError(
                        "La risposta del provider non contiene access_token."
                    )
                key = f"connector:{descriptor.id}"
                if on_token is None:
                    secret_store.set(key, access_token)
                else:
                    on_token(access_token)
                refresh_token = token_data.get("refresh_token")
                if isinstance(refresh_token, str) and refresh_token:
                    secret_store.set(f"{key}:refresh_token", refresh_token)
                expires_in = token_data.get("expires_in")
                if isinstance(expires_in, (int, float)) and expires_in > 0:
                    secret_store.set(
                        f"{key}:expires_at",
                        str(time.time() + float(expires_in)),
                    )
                self._respond(200, "Jarvis è connesso. Puoi chiudere questa finestra.")
                logging.getLogger(__name__).info(
                    "OAuth callback completed for connector %s.",
                    descriptor.id,
                )
            except HTTPError as exc:
                provider_code = ""
                provider_description = ""
                try:
                    response_body = json.loads(exc.read(16_384).decode("utf-8"))
                    if isinstance(response_body, dict):
                        provider_code = str(response_body.get("error", ""))[:100]
                        provider_description = str(
                            response_body.get("error_description", "")
                        )[:300]
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                message = _failure_details(
                    descriptor,
                    error_code=provider_code,
                    description=provider_description,
                    status=exc.code,
                )
                self._fail(exc.code, message, error_code=provider_code, exc=exc)
            except (URLError, TimeoutError, HTTPException, OSError) as exc:
                message = (
                    f"Impossibile completare la connessione OAuth: "
                    f"{type(exc).__name__}."
                )
                self._fail(502, message, error_code=type(exc).__name__, exc=exc)
            except OAuthFlowError as exc:
                self._fail(
                    502,
                    str(exc),
                    error_code="invalid_token_response",
                    exc=exc,
                )
            except Exception as exc:
                message = (
                    f"Risposta OAuth non valida: {type(exc).__name__}. "
                    "Controlla la configurazione del provider."
                )
                self._fail(502, message, error_code=type(exc).__name__, exc=exc)
            finally:
                completed.set()

        def _fail(
            self,
            status: int,
            message: str,
            *,
            error_code: str,
            exc: Exception | None = None,
        ) -> None:
            logger = logging.getLogger(__name__)
            for sensitive_value in (client_secret, client_id, verifier, state):
                if sensitive_value:
                    message = message.replace(sensitive_value, "[redacted]")
            if exc is not None:
                logger.warning(
                    "OAuth callback failed for connector %s (HTTP %s, %s): %s",
                    descriptor.id,
                    status,
                    error_code or type(exc).__name__,
                    message,
                )
            else:
                logger.warning(
                    "OAuth callback failed for connector %s (%s): %s",
                    descriptor.id,
                    error_code,
                    message,
                )
            if on_error is not None:
                try:
                    on_error(message)
                except Exception:
                    logger.exception(
                        "OAuth error callback failed for connector %s.",
                        descriptor.id,
                    )
            self._respond(status, message)

        def _respond(self, status: int, message: str) -> None:
            payload = (
                "<!doctype html><meta charset=utf-8>"
                "<title>Jarvis OAuth</title>"
                "<p>" + html.escape(message) + "</p>"
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _respond_json(self, status: int, body: dict[str, str]) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format: str, *args) -> None:
            return

    class CallbackHTTPServer(ThreadingHTTPServer):
        allow_reuse_address = True

    listener, _time_wait = _callback_port_state(redirect.hostname, redirect.port)
    if listener:
        raise OAuthFlowError(
            f"OAuth callback port {redirect.port} is already in use on "
            f"{redirect.hostname} by {listener}. Close that process, then retry."
        )
    listener = _wait_for_callback_time_wait(redirect.hostname, redirect.port)
    if listener:
        raise OAuthFlowError(
            f"OAuth callback port {redirect.port} is already in use on "
            f"{redirect.hostname} by {listener}. Close that process, then retry."
        )

    server = None
    bind_error = None
    for attempt in range(1, _CALLBACK_BIND_ATTEMPTS + 1):
        try:
            server = CallbackHTTPServer(
                (redirect.hostname, redirect.port),
                CallbackHandler,
            )
            break
        except OSError as exc:
            bind_error = exc
            listener, _time_wait = _callback_port_state(
                redirect.hostname,
                redirect.port,
            )
            if listener:
                raise OAuthFlowError(
                    f"OAuth callback port {redirect.port} is already in use on "
                    f"{redirect.hostname} by {listener}. Close that process, "
                    "then retry."
                ) from exc
            if attempt < _CALLBACK_BIND_ATTEMPTS:
                logger.warning(
                    "OAuth callback bind attempt %s/%s failed for %s:%s (%s); "
                    "retrying in %.0f second.",
                    attempt,
                    _CALLBACK_BIND_ATTEMPTS,
                    redirect.hostname,
                    redirect.port,
                    type(exc).__name__,
                    _CALLBACK_BIND_RETRY_DELAY,
                )
                time.sleep(_CALLBACK_BIND_RETRY_DELAY)
    if server is None:
        if (
            bind_error
            and (
                bind_error.errno == errno.EADDRINUSE
                or getattr(bind_error, "winerror", None) == 10048
            )
        ):
            raise OAuthFlowError(
                f"OAuth callback port {redirect.port} is unavailable on "
                f"{redirect.hostname} after {_CALLBACK_BIND_ATTEMPTS} attempts. "
                "Check for another process using it."
            ) from bind_error
        raise OAuthFlowError(
            f"OAuth callback server could not bind to "
            f"{descriptor.redirect_uri} after {_CALLBACK_BIND_ATTEMPTS} "
            f"attempts ({type(bind_error).__name__ if bind_error else 'unknown error'})."
        ) from bind_error
    server.daemon_threads = True

    def serve_callback_server() -> None:
        try:
            server_ready.set()
            server.serve_forever()
        except Exception as exc:
            logger.exception(
                "OAuth callback server crashed for connector %s.",
                descriptor.id,
            )
            if on_error is not None:
                try:
                    on_error(
                        "Il server callback OAuth si è arrestato in modo "
                        f"inatteso ({type(exc).__name__})."
                    )
                except Exception:
                    logger.exception(
                        "OAuth error callback failed after server crash for "
                        "connector %s.",
                        descriptor.id,
                    )
        finally:
            completed.set()

    server_thread = threading.Thread(
        target=serve_callback_server,
        daemon=True,
        name=f"oauth-callback-{descriptor.id}",
    )
    server_ready = threading.Event()
    server_thread.start()
    if not server_ready.wait(timeout=2) or not server_thread.is_alive() or completed.is_set():
        server.server_close()
        raise OAuthFlowError(
            f"OAuth callback server failed to start on "
            f"{redirect.hostname}:{redirect.port}; browser was not opened."
        )
    logger.info(
        "OAuth callback server listening on %s:%s%s for connector %s.",
        redirect.hostname,
        redirect.port,
        redirect.path,
        descriptor.id,
    )
    logger.info(
        "OAuth authorization prepared for connector %s: client_id_present=%s "
        "redirect_uri=%s",
        descriptor.id,
        bool(client_id),
        descriptor.redirect_uri,
    )
    if descriptor.id == "google-workspace":
        print(
            "URL autorizzazione Google: "
            f"{_redacted_authorization_url(authorization_url, show_client_id=True)}",
            flush=True,
        )

    def stop_server() -> None:
        completed.wait(timeout)
        server.shutdown()
        server.server_close()

    threading.Thread(
        target=stop_server,
        daemon=True,
        name=f"oauth-timeout-{descriptor.id}",
    ).start()

    return authorization_url

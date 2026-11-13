"""
Connector catalogue: descriptors, persistent state, scopes, auth lifecycle.

A connector is *infrastructure* (an MCP server reached over some transport),
not an implementation. The registry stores descriptors and their state, checks
scopes before every call, audits it, and never holds a secret itself: tokens go
through ``SecretStore``. Lifecycle: enable -> authenticate -> scope -> revoke.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from core.audit_log import AuditLog
from core.secret_store import SecretStore

TYPES = ("first-party", "remote-api", "remote-mcp", "custom-mcp", "local-mcp")
TRANSPORTS = ("api", "streamable-http", "sse", "stdio")
AUTH_KINDS = ("oauth2", "api-key", "none")
STATUSES = ("disconnected", "connected", "error", "expired")
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


class ConnectorError(Exception):
    pass


@dataclass
class ConnectorDescriptor:
    id: str
    name: str
    type: str
    transport: str
    auth: str
    scopes: list[str] = field(default_factory=list)
    # namespaced tool -> scope it needs, e.g. {"gmail.search": "gmail.read"}
    tool_refs: dict[str, str] = field(default_factory=dict)
    endpoint: str = ""
    authorize_url: str = ""
    token_url: str = ""
    registration_url: str = ""
    oauth_resource: str = ""
    client_id_env: str = ""
    client_secret_env: str = ""
    redirect_uri: str = ""
    oauth_setup_url: str = ""
    oauth_scopes: list[str] = field(default_factory=list)
    authorize_params: dict[str, str] = field(default_factory=dict)
    tool_map: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not _ID_RE.match(self.id):
            raise ConnectorError(f"Invalid connector id: {self.id!r}")
        if self.type not in TYPES:
            raise ConnectorError(f"{self.id}: unknown type {self.type!r}")
        if self.transport not in TRANSPORTS:
            raise ConnectorError(f"{self.id}: unknown transport {self.transport!r}")
        if self.auth not in AUTH_KINDS:
            raise ConnectorError(f"{self.id}: unknown auth {self.auth!r}")
        for tool, scope in self.tool_refs.items():
            if scope not in self.scopes:
                raise ConnectorError(f"{self.id}: tool {tool} needs undeclared scope {scope}")
        if self.auth == "oauth2":
            reserved_oauth_params = {
                "response_type",
                "client_id",
                "redirect_uri",
                "scope",
                "state",
                "code_challenge",
                "code_challenge_method",
                "resource",
            }
            if reserved_oauth_params & self.authorize_params.keys():
                raise ConnectorError(
                    f"{self.id}: authorize_params cannot override OAuth security parameters"
                )
            if self.oauth_resource:
                resource = urlsplit(self.oauth_resource)
                if (
                    resource.scheme != "https"
                    or not resource.hostname
                    or resource.username is not None
                    or resource.password is not None
                ):
                    raise ConnectorError(
                        f"{self.id}: oauth_resource must be an HTTPS URL without credentials"
                    )
            for label, url in (
                ("authorize_url", self.authorize_url),
                ("token_url", self.token_url),
                ("registration_url", self.registration_url),
                ("oauth_setup_url", self.oauth_setup_url),
            ):
                if url:
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme != "https"
                        or not parsed.hostname
                        or parsed.username is not None
                        or parsed.password is not None
                    ):
                        raise ConnectorError(
                            f"{self.id}: {label} must be an HTTPS URL without credentials"
                        )

    @classmethod
    def from_dict(cls, data: dict) -> "ConnectorDescriptor":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        descriptor = cls(**known)
        descriptor.validate()
        return descriptor


class ConnectorAuth:
    """Provider-specific part of the auth lifecycle."""

    def begin_oauth(
        self,
        descriptor: ConnectorDescriptor,
        on_token: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> str:
        raise NotImplementedError

    def complete(self, descriptor: ConnectorDescriptor, token: str) -> None:
        raise NotImplementedError

    def refresh(self, descriptor: ConnectorDescriptor) -> bool:
        raise NotImplementedError

    def revoke(self, descriptor: ConnectorDescriptor) -> None:
        raise NotImplementedError

    def status(self, descriptor: ConnectorDescriptor) -> str:
        raise NotImplementedError


class SecretStoreAuth(ConnectorAuth):
    """Default auth: the token (OAuth access token or API key) lives in the SecretStore."""

    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets
        self._refresh_lock = threading.Lock()

    @staticmethod
    def _key(descriptor: ConnectorDescriptor) -> str:
        return f"connector:{descriptor.id}"

    def begin_oauth(
        self,
        descriptor: ConnectorDescriptor,
        on_token: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> str:
        if descriptor.auth != "oauth2":
            raise ConnectorError(f"{descriptor.id}: OAuth is not enabled")
        from core.oauth_flow import OAuthFlowError, begin_loopback_oauth

        try:
            return begin_loopback_oauth(
                descriptor,
                self._secrets,
                on_token=on_token,
                on_error=on_error,
            )
        except OAuthFlowError as exc:
            raise ConnectorError(str(exc)) from exc

    def complete(self, descriptor, token):
        if descriptor.auth == "none":
            return
        if not token:
            raise ConnectorError(f"{descriptor.id}: empty token")
        self._secrets.set(self._key(descriptor), token)

    def refresh(self, descriptor):
        return self.access_token(descriptor) is not None

    def oauth_credentials(self, descriptor: ConnectorDescriptor) -> tuple[str, str]:
        key = self._key(descriptor)
        client_id = (
            os.environ.get(descriptor.client_id_env, "").strip()
            if descriptor.client_id_env
            else ""
        ) or (self._secrets.get(f"{key}:client_id") or "").strip()
        client_secret = (
            os.environ.get(descriptor.client_secret_env, "").strip()
            if descriptor.client_secret_env
            else ""
        ) or (self._secrets.get(f"{key}:client_secret") or "")
        return client_id, client_secret

    def save_oauth_credentials(
        self,
        descriptor: ConnectorDescriptor,
        client_id: str,
        client_secret: str,
    ) -> None:
        if descriptor.auth != "oauth2":
            raise ConnectorError(f"{descriptor.name} does not use OAuth.")
        client_id = client_id.strip()
        client_secret = client_secret.strip()
        if not client_id:
            raise ConnectorError("Il Client ID è obbligatorio.")
        _, configured_secret = self.oauth_credentials(descriptor)
        if descriptor.client_secret_env and not client_secret and not configured_secret:
            raise ConnectorError("Il Client Secret è obbligatorio per questo servizio.")
        key = self._key(descriptor)
        self._secrets.set(f"{key}:client_id", client_id)
        if client_secret:
            self._secrets.set(f"{key}:client_secret", client_secret)

    def save_personal_access_token(
        self,
        descriptor: ConnectorDescriptor,
        token: str,
    ) -> None:
        if descriptor.id != "github":
            raise ConnectorError(
                "Manual Personal Access Tokens are currently supported only for GitHub."
            )
        token = token.strip()
        if not token:
            raise ConnectorError("Il Personal Access Token è obbligatorio.")
        key = self._key(descriptor)
        self._secrets.set(key, token)
        self._secrets.delete(f"{key}:refresh_token")
        self._secrets.delete(f"{key}:expires_at")

    def access_token(
        self, descriptor: ConnectorDescriptor, *, force_refresh: bool = False
    ) -> str | None:
        key = self._key(descriptor)
        access_token = self._secrets.get(key)
        expires_at = self._secrets.get(f"{key}:expires_at")
        try:
            is_expiring = expires_at is not None and float(expires_at) <= time.time() + 30
        except ValueError:
            is_expiring = True
        if not access_token or (not is_expiring and not force_refresh):
            return access_token

        refresh_token = self._secrets.get(f"{key}:refresh_token")
        if not refresh_token:
            raise ConnectorError(
                f"{descriptor.name}: token scaduto o rifiutato e refresh token non disponibile."
            )
        with self._refresh_lock:
            current_token = self._secrets.get(key)
            if force_refresh and current_token != access_token:
                return current_token
            expires_at = self._secrets.get(f"{key}:expires_at")
            try:
                is_expiring = expires_at is not None and float(expires_at) <= time.time() + 30
            except ValueError:
                is_expiring = True
            if not is_expiring and not force_refresh:
                return current_token
            refresh_token = self._secrets.get(f"{key}:refresh_token")
            if not refresh_token:
                raise ConnectorError(f"{descriptor.name}: refresh token non disponibile.")
            client_id, client_secret = self.oauth_credentials(descriptor)
            if not client_id or not descriptor.token_url:
                raise ConnectorError(
                    f"{descriptor.name}: configurazione OAuth incompleta per il rinnovo del token."
                )
            from urllib.parse import urlencode
            from urllib.request import Request, urlopen

            body = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            }
            if descriptor.oauth_resource:
                body["resource"] = descriptor.oauth_resource
            if client_secret:
                body["client_secret"] = client_secret
            request = Request(
                descriptor.token_url,
                data=urlencode(body).encode("ascii"),
                headers={"Accept": "application/json",
                         "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            try:
                with urlopen(request, timeout=20) as response:
                    token_data = json.loads(response.read(64_000).decode("utf-8"))
            except Exception as exc:
                raise ConnectorError(
                    f"{descriptor.name} token refresh failed ({type(exc).__name__})."
                ) from exc
            new_access_token = token_data.get("access_token")
            if not isinstance(new_access_token, str) or not new_access_token:
                raise ConnectorError(f"{descriptor.name} refresh response has no access token.")
            self._secrets.set(key, new_access_token)
            new_refresh_token = token_data.get("refresh_token")
            if isinstance(new_refresh_token, str) and new_refresh_token:
                self._secrets.set(f"{key}:refresh_token", new_refresh_token)
            if token_data.get("expires_in") is not None:
                self._secrets.set(
                    f"{key}:expires_at",
                    str(time.time() + int(token_data["expires_in"])),
                )
            else:
                self._secrets.delete(f"{key}:expires_at")
            return new_access_token

    def revoke(self, descriptor):
        key = self._key(descriptor)
        for suffix in ("", ":refresh_token", ":expires_at"):
            self._secrets.delete(f"{key}{suffix}")

    def status(self, descriptor):
        if descriptor.auth == "none":
            return "connected"
        return "connected" if self._secrets.get(self._key(descriptor)) else "disconnected"


class ScopeManager:
    """Scopes are declared by the descriptor and granted by the user, never by the LLM."""

    def __init__(self) -> None:
        self._granted: dict[str, set[str]] = {}

    def load(self, granted: dict[str, list[str]]) -> None:
        self._granted = {k: set(v) for k, v in granted.items()}

    def dump(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self._granted.items() if v}

    def grant(self, descriptor: ConnectorDescriptor, scopes: list[str]) -> None:
        undeclared = set(scopes) - set(descriptor.scopes)
        if undeclared:
            raise ConnectorError(f"{descriptor.id}: undeclared scopes {sorted(undeclared)}")
        self._granted.setdefault(descriptor.id, set()).update(scopes)

    def clear(self, connector_id: str) -> None:
        self._granted.pop(connector_id, None)

    def granted(self, connector_id: str) -> set[str]:
        return set(self._granted.get(connector_id, ()))

    def allows(self, connector_id: str, scope: str) -> bool:
        return scope in self._granted.get(connector_id, ())


class ConnectorRegistry:
    def __init__(self, state_path: Path, secrets: SecretStore, audit: AuditLog,
                 auth: ConnectorAuth | None = None) -> None:
        self._state_path = Path(state_path)
        self._audit = audit
        self._auth = auth or SecretStoreAuth(secrets)
        self._descriptors: dict[str, ConnectorDescriptor] = {}
        self._errors: dict[str, str] = {}
        self._oauth_pending: set[str] = set()
        self._invokers: dict[str, Callable[[str, dict], object]] = {}
        self._on_revoke: list[Callable[[str], None]] = []
        self._state_lock = threading.RLock()
        self.scopes = ScopeManager()
        self.scopes.load(self._read_state().get("granted", {}))

    # -- persistence --
    def _read_state(self) -> dict:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self) -> None:
        with self._state_lock:
            state = {"granted": self.scopes.dump(), "errors": self._errors}
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(state, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    # -- catalogue --
    def register(self, descriptor: ConnectorDescriptor,
                 invoker: Callable[[str, dict], object] | None = None) -> None:
        descriptor.validate()
        if descriptor.id in self._descriptors:
            raise ConnectorError(f"Connector {descriptor.id} already registered")
        self._descriptors[descriptor.id] = descriptor
        if invoker:
            self._invokers[descriptor.id] = invoker

    def load_catalog(self, directory: Path) -> list[str]:
        loaded = []
        for path in sorted(Path(directory).glob("*.json")):
            try:
                self.register(ConnectorDescriptor.from_dict(json.loads(path.read_text(encoding="utf-8"))))
                loaded.append(path.stem)
            except (OSError, json.JSONDecodeError, ConnectorError, TypeError) as exc:
                self._errors[path.stem] = str(exc)
        return loaded

    def set_invoker(self, connector_id: str, invoker: Callable[[str, dict], object]) -> None:
        self.get(connector_id)
        self._invokers[connector_id] = invoker

    def on_revoke(self, callback: Callable[[str], None]) -> None:
        self._on_revoke.append(callback)

    def get(self, connector_id: str) -> ConnectorDescriptor:
        try:
            return self._descriptors[connector_id]
        except KeyError:
            raise ConnectorError(f"Unknown connector {connector_id!r}") from None

    # -- lifecycle --
    def status(self, connector_id: str) -> str:
        descriptor = self.get(connector_id)
        if connector_id in self._errors:
            return "error"
        return self._auth.status(descriptor)

    def access_token(self, connector_id: str, *, force_refresh: bool = False) -> str | None:
        descriptor = self.get(connector_id)
        if isinstance(self._auth, SecretStoreAuth):
            return self._auth.access_token(descriptor, force_refresh=force_refresh)
        return None

    def save_oauth_credentials(
        self,
        connector_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        descriptor = self.get(connector_id)
        if not isinstance(self._auth, SecretStoreAuth):
            raise ConnectorError("OAuth credentials cannot be stored by this auth provider.")
        self._auth.save_oauth_credentials(descriptor, client_id, client_secret)
        self._audit.record(
            tool="connector.save_oauth_credentials",
            connector=connector_id,
            outcome="ok",
        )

    def save_personal_access_token(
        self,
        connector_id: str,
        token: str,
    ) -> None:
        if connector_id != "github":
            raise ConnectorError(
                "Manual Personal Access Tokens are currently supported only for GitHub."
            )
        descriptor = self.get(connector_id)
        if descriptor.auth != "oauth2":
            raise ConnectorError(f"{descriptor.name} does not support token authentication.")
        token = token.strip()
        if not token:
            raise ConnectorError("Il Personal Access Token è obbligatorio.")
        if not isinstance(self._auth, SecretStoreAuth):
            raise ConnectorError(
                "The configured credential provider cannot store a GitHub token."
            )

        self._auth.save_personal_access_token(descriptor, token)
        with self._state_lock:
            self._errors.pop(connector_id, None)
            self._oauth_pending.discard(connector_id)
            self._write_state()
            self._audit.record(
                tool="connector.save_personal_access_token",
                connector=connector_id,
                outcome="ok",
            )

    def begin_oauth(self, connector_id: str) -> str:
        """Return the authorization URL only after the loopback server starts."""
        descriptor = self.get(connector_id)
        with self._state_lock:
            self._errors.pop(connector_id, None)
            self._oauth_pending.add(connector_id)
            self._write_state()

        def report_error(message: str) -> None:
            with self._state_lock:
                self._oauth_pending.discard(connector_id)
                self._errors[connector_id] = message
                self._write_state()
                self._audit.record(
                    tool="connector.oauth_callback",
                    connector=connector_id,
                    outcome="error",
                    detail=message[:500],
                )

        try:
            if isinstance(self._auth, SecretStoreAuth):
                return self._auth.begin_oauth(
                    descriptor,
                    on_token=lambda token: self.authenticate(connector_id, token),
                    on_error=report_error,
                )
            return self._auth.begin_oauth(descriptor, on_error=report_error)
        except Exception:
            self.cancel_oauth(connector_id)
            raise

    def cancel_oauth(self, connector_id: str) -> None:
        """Clear the UI's pending marker when an authorization page cannot be opened."""
        self.get(connector_id)
        with self._state_lock:
            self._oauth_pending.discard(connector_id)

    def oauth_configured(self, connector_id: str) -> bool:
        descriptor = self.get(connector_id)
        with self._state_lock:
            client_id, client_secret = self._oauth_credentials(descriptor)
            return bool(
                descriptor.auth == "oauth2"
                and descriptor.authorize_url
                and descriptor.token_url
                and (bool(descriptor.registration_url) or bool(client_id))
                and (
                    bool(descriptor.registration_url)
                    or not descriptor.client_secret_env
                    or bool(client_secret)
                )
                and descriptor.redirect_uri
                and descriptor.oauth_scopes
            )

    def _oauth_credentials(self, descriptor: ConnectorDescriptor) -> tuple[str, str]:
        if isinstance(self._auth, SecretStoreAuth):
            return self._auth.oauth_credentials(descriptor)
        client_id = (
            os.environ.get(descriptor.client_id_env, "").strip()
            if descriptor.client_id_env
            else ""
        )
        client_secret = (
            os.environ.get(descriptor.client_secret_env, "").strip()
            if descriptor.client_secret_env
            else ""
        )
        return client_id, client_secret

    def authenticate(self, connector_id: str, token: str = "") -> str:
        descriptor = self.get(connector_id)
        with self._state_lock:
            self._auth.complete(descriptor, token)
            self._oauth_pending.discard(connector_id)
            self._errors.pop(connector_id, None)
            self._write_state()
            self._audit.record(
                tool="connector.authenticate",
                connector=connector_id,
                outcome="ok",
            )
        return self.status(connector_id)

    def grant(self, connector_id: str, scopes: list[str]) -> None:
        with self._state_lock:
            self.scopes.grant(self.get(connector_id), scopes)
            self._write_state()
            self._audit.record(
                tool="connector.grant",
                connector=connector_id,
                outcome="ok",
                detail=",".join(scopes),
            )

    def set_scopes(self, connector_id: str, scopes: list[str]) -> None:
        descriptor = self.get(connector_id)
        requested = set(scopes)
        undeclared = requested - set(descriptor.scopes)
        if undeclared:
            raise ConnectorError(
                f"{connector_id}: undeclared scopes {sorted(undeclared)}"
            )
        with self._state_lock:
            self.scopes.clear(connector_id)
            self.scopes.grant(descriptor, sorted(requested))
            self._write_state()
            self._audit.record(
                tool="connector.set_scopes",
                connector=connector_id,
                outcome="ok",
                detail=",".join(sorted(requested)),
            )

    def revoke(self, connector_id: str) -> None:
        descriptor = self.get(connector_id)
        with self._state_lock:
            self._auth.revoke(descriptor)
            self.scopes.clear(connector_id)
            self._errors.pop(connector_id, None)
            self._write_state()
            self._audit.record(
                tool="connector.revoke",
                connector=connector_id,
                outcome="ok",
            )
        for callback in self._on_revoke:
            callback(connector_id)

    # -- tools --
    def tool_scope(self, tool_ref: str) -> tuple[ConnectorDescriptor, str]:
        for descriptor in self._descriptors.values():
            if tool_ref in descriptor.tool_refs:
                return descriptor, descriptor.tool_refs[tool_ref]
        raise ConnectorError(f"Unknown tool {tool_ref!r}")

    def tool_ready(self, tool_ref: str) -> tuple[bool, str]:
        """(ok, reason) for a skill that wants to use ``tool_ref``."""
        try:
            descriptor, scope = self.tool_scope(tool_ref)
        except ConnectorError as exc:
            return False, str(exc)
        if self.status(descriptor.id) != "connected":
            return False, f"Connector '{descriptor.name}' is not connected."
        if not self.scopes.allows(descriptor.id, scope):
            return False, f"Scope '{scope}' of '{descriptor.name}' has not been granted."
        return True, ""

    def call_tool(self, tool_ref: str, arguments: dict | None = None, skill: str | None = None):
        arguments = arguments or {}
        if tool_ref == "github.search_repositories" and not any(
            isinstance(arguments.get(key), str) and arguments[key].strip()
            for key in ("q", "query", "search_query")
        ):
            raise ConnectorError(
                "Specifica una query di ricerca oppure usa "
                "github_user_repositories per elencare i repository dell'utente "
                "GitHub autenticato."
            )
        ok, reason = self.tool_ready(tool_ref)
        descriptor = None
        scope = None
        try:
            descriptor, scope = self.tool_scope(tool_ref)
        except ConnectorError:
            pass
        connector_id = descriptor.id if descriptor else None
        if not ok:
            self._audit.record(tool=tool_ref, connector=connector_id, skill=skill, scope=scope,
                               arguments=arguments, outcome="denied", detail=reason)
            raise ConnectorError(reason)
        invoker = self._invokers.get(descriptor.id)
        if invoker is None:
            reason = f"Connector '{descriptor.name}' has no transport attached."
            self._audit.record(tool=tool_ref, connector=connector_id, skill=skill, scope=scope,
                               arguments=arguments, outcome="error", detail=reason)
            raise ConnectorError(reason)
        try:
            result = invoker(tool_ref, arguments)
        except Exception as exc:
            self._audit.record(tool=tool_ref, connector=connector_id, skill=skill, scope=scope,
                               arguments=arguments, outcome="error", detail=str(exc))
            raise
        self._audit.record(tool=tool_ref, connector=connector_id, skill=skill, scope=scope,
                           arguments=arguments, outcome="ok")
        return result

    # -- UI projection (read-only) --
    def view(self) -> list[dict]:
        return [
            {
                "id": d.id,
                "name": d.name,
                "type": d.type,
                "transport": d.transport,
                "auth": d.auth,
                "status": self.status(d.id),
                "oauth_configured": self.oauth_configured(d.id),
                "oauth_client_id": self._oauth_credentials(d)[0],
                "oauth_redirect_uri": d.redirect_uri,
                "oauth_dynamic_registration": bool(d.registration_url),
                "oauth_requires_client_secret": bool(d.client_secret_env),
                "oauth_setup": [
                    name
                    for name, value in zip(
                        (d.client_id_env, d.client_secret_env),
                        self._oauth_credentials(d),
                        strict=True,
                    )
                    if name and not value and not d.registration_url
                ],
                "oauth_setup_url": d.oauth_setup_url,
                "oauth_error": self._errors.get(d.id, ""),
                "oauth_pending": d.id in self._oauth_pending,
                "transport_configured": (
                    bool(d.endpoint)
                    if d.transport == "streamable-http"
                    else d.id in self._invokers
                    if d.transport in {"api", "stdio"}
                    else True
                ),
                "scopes_declared": list(d.scopes),
                "scopes_granted": sorted(self.scopes.granted(d.id)),
                "tools": sorted(d.tool_refs),
            }
            for d in self._descriptors.values()
        ]

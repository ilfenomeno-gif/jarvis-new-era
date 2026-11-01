"""
Connector catalogue: descriptors, persistent state, scopes, auth lifecycle.

A connector is *infrastructure* (an MCP server reached over some transport),
not an implementation. The registry stores descriptors and their state, checks
scopes before every call, audits it, and never holds a secret itself: tokens go
through ``SecretStore``. Lifecycle: enable -> authenticate -> scope -> revoke.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.audit_log import AuditLog
from core.secret_store import SecretStore

TYPES = ("first-party", "remote-mcp", "custom-mcp", "local-mcp")
TRANSPORTS = ("streamable-http", "sse", "stdio")
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

    @classmethod
    def from_dict(cls, data: dict) -> "ConnectorDescriptor":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        descriptor = cls(**known)
        descriptor.validate()
        return descriptor


class ConnectorAuth:
    """Provider-specific part of the auth lifecycle."""

    def begin_oauth(self, descriptor: ConnectorDescriptor) -> str:
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

    @staticmethod
    def _key(descriptor: ConnectorDescriptor) -> str:
        return f"connector:{descriptor.id}"

    def begin_oauth(self, descriptor):
        if descriptor.auth != "oauth2" or not descriptor.authorize_url:
            raise ConnectorError(f"{descriptor.id}: no OAuth authorize URL configured")
        return descriptor.authorize_url

    def complete(self, descriptor, token):
        if descriptor.auth == "none":
            return
        if not token:
            raise ConnectorError(f"{descriptor.id}: empty token")
        self._secrets.set(self._key(descriptor), token)

    def refresh(self, descriptor):
        # Refresh needs provider code; without it the token is reported as unchanged.
        return self._secrets.get(self._key(descriptor)) is not None

    def revoke(self, descriptor):
        self._secrets.delete(self._key(descriptor))

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
        self._invokers: dict[str, Callable[[str, dict], object]] = {}
        self._on_revoke: list[Callable[[str], None]] = []
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
        state = {"granted": self.scopes.dump(), "errors": self._errors}
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

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

    def begin_oauth(self, connector_id: str) -> str:
        return self._auth.begin_oauth(self.get(connector_id))

    def authenticate(self, connector_id: str, token: str = "") -> str:
        descriptor = self.get(connector_id)
        self._auth.complete(descriptor, token)
        self._errors.pop(connector_id, None)
        self._write_state()
        self._audit.record(tool="connector.authenticate", connector=connector_id, outcome="ok")
        return self.status(connector_id)

    def grant(self, connector_id: str, scopes: list[str]) -> None:
        self.scopes.grant(self.get(connector_id), scopes)
        self._write_state()
        self._audit.record(tool="connector.grant", connector=connector_id, outcome="ok",
                           detail=",".join(scopes))

    def revoke(self, connector_id: str) -> None:
        descriptor = self.get(connector_id)
        self._auth.revoke(descriptor)
        self.scopes.clear(connector_id)
        self._errors.pop(connector_id, None)
        self._write_state()
        self._audit.record(tool="connector.revoke", connector=connector_id, outcome="ok")
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
                "scopes_declared": list(d.scopes),
                "scopes_granted": sorted(self.scopes.granted(d.id)),
                "tools": sorted(d.tool_refs),
            }
            for d in self._descriptors.values()
        ]

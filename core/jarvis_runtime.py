"""Lazily-built singletons shared by the skill/connector actions."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from core.audit_log import AuditLog
from core.connectors import ConnectorRegistry, SecretStoreAuth
from core.mcp_transport import HttpMcpInvoker
from core.secret_store import SecretStore
from core.skill_router import SkillRouter
from core.skills import SkillRegistry

BASE_DIR = Path(__file__).resolve().parents[1]
_lock = threading.Lock()
_runtime: "Runtime | None" = None


@dataclass
class Runtime:
    secrets: SecretStore
    audit: AuditLog
    connectors: ConnectorRegistry
    skills: SkillRegistry
    router: SkillRouter


def build_runtime(base: Path = BASE_DIR, secrets: SecretStore | None = None) -> Runtime:
    config = base / "config"
    secrets = secrets or SecretStore(config / "secrets.json")
    audit = AuditLog(config / "audit.jsonl")
    connectors = ConnectorRegistry(config / "connectors_state.json", secrets, audit,
                                   SecretStoreAuth(secrets))
    connectors.load_catalog(base / "connectors" / "catalog")
    for item in connectors.view():
        descriptor = connectors.get(item["id"])
        if descriptor.transport == "streamable-http" and descriptor.endpoint:
            key = f"connector:{descriptor.id}"
            connectors.set_invoker(descriptor.id, HttpMcpInvoker(
                descriptor.endpoint, lambda key=key: secrets.get(key)))
    skills = SkillRegistry(base / "skills", config / "skills_state.json", audit)
    skills.load()
    connectors.on_revoke(lambda cid: skills.disable_for_connector(cid, connectors))
    return Runtime(secrets, audit, connectors, skills, SkillRouter(skills, connectors))


def get_runtime() -> Runtime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = build_runtime()
        return _runtime

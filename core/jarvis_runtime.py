"""Lazily-built singletons shared by the skill/connector actions."""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from core.audit_log import AuditLog
from core.connectors import ConnectorRegistry, SecretStoreAuth
from core.env_config import load_env_file
from core.mcp_transport import HttpMcpInvoker
from core.public_apis_catalog import PublicApisCatalog
from core.secret_store import SecretStore
from core.skill_router import SkillRouter
from core.skills import SkillRegistry
from core.watchdog import ProcessWatchdog

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
    public_apis: PublicApisCatalog
    watchdog: ProcessWatchdog


def build_runtime(base: Path = BASE_DIR, secrets: SecretStore | None = None) -> Runtime:
    load_env_file(base / ".env")
    google_client_id = os.environ.get("JARVIS_GOOGLE_CLIENT_ID", "").strip()
    logger = logging.getLogger(__name__)
    logger.info(
        "Google Client ID letto: %s",
        "SI" if google_client_id else "NO",
    )
    if google_client_id:
        prefix = google_client_id[:min(10, len(google_client_id) - 1)]
        logger.info(
            "[DEBUG] Cerco JARVIS_GOOGLE_CLIENT_ID... Trovato: SI. "
            "Lunghezza: %d caratteri. Primi caratteri: %s...",
            len(google_client_id),
            prefix.encode("unicode_escape").decode("ascii"),
        )
    else:
        logger.info("[DEBUG] Cerco JARVIS_GOOGLE_CLIENT_ID... Trovato: NO")
    config = base / "config"
    secrets = secrets or SecretStore(config / "secrets.json")
    audit = AuditLog(config / "audit.jsonl")
    connectors = ConnectorRegistry(config / "connectors_state.json", secrets, audit,
                                   SecretStoreAuth(secrets))
    connectors.load_catalog(base / "connectors" / "catalog")
    public_apis = PublicApisCatalog(connectors, base)
    watchdog = ProcessWatchdog(logger=print)
    watchdog.register(
        "public-apis-mcp",
        public_apis.watchdog_healthy,
        public_apis.recover_stopped_process,
    )
    for item in connectors.view():
        descriptor = connectors.get(item["id"])
        if descriptor.transport == "streamable-http" and descriptor.endpoint:
            connectors.set_invoker(descriptor.id, HttpMcpInvoker(
                descriptor.endpoint,
                lambda connector_id=descriptor.id: connectors.access_token(connector_id),
                tool_map=descriptor.tool_map,
                timeout=60.0 if descriptor.id == "canva" else 30.0,
            ))
        elif descriptor.transport == "api" and descriptor.id == "spotify":
            from core.spotify_transport import SpotifyApiInvoker

            connectors.set_invoker(
                descriptor.id,
                SpotifyApiInvoker(
                    lambda connector_id=descriptor.id: connectors.access_token(
                        connector_id
                    )
                ),
            )
        elif descriptor.transport == "api" and descriptor.id == "google-workspace":
            from core.google_workspace_transport import GoogleWorkspaceApiInvoker

            connectors.set_invoker(
                descriptor.id,
                GoogleWorkspaceApiInvoker(
                    lambda: connectors.access_token("google-workspace"),
                    lambda: connectors.access_token("google-workspace", force_refresh=True),
                ),
            )
    skills = SkillRegistry(base / "skills", config / "skills_state.json", audit)
    skills.load()
    connectors.on_revoke(lambda cid: skills.disable_for_connector(cid, connectors))
    runtime = Runtime(
        secrets,
        audit,
        connectors,
        skills,
        SkillRouter(skills, connectors),
        public_apis,
        watchdog,
    )
    watchdog.start()
    return runtime


def get_runtime() -> Runtime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = build_runtime()
        return _runtime


def shutdown_runtime() -> None:
    if _runtime is not None:
        _runtime.watchdog.stop()
        _runtime.public_apis.stop()

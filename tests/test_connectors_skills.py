"""Tests for SecretStore, connectors, skills and routing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.audit_log import AuditLog
from core.connectors import ConnectorDescriptor, ConnectorError, ConnectorRegistry
from core.secret_store import SecretStore
from core.skill_router import SkillRouter, classify_intent
from core.skills import SkillError, SkillRegistry, parse_frontmatter

ROOT = Path(__file__).resolve().parents[1]


class FakeBackend:
    def protect(self, data: bytes) -> bytes:
        return b"enc:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[len(b"enc:"):][::-1]


@pytest.fixture
def env(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json", FakeBackend())
    audit = AuditLog(tmp_path / "audit.jsonl")
    connectors = ConnectorRegistry(tmp_path / "connectors.json", secrets, audit)
    connectors.load_catalog(ROOT / "connectors" / "catalog")
    return secrets, audit, connectors, tmp_path


def test_secret_store_never_writes_plaintext(tmp_path):
    store = SecretStore(tmp_path / "s.json", FakeBackend())
    store.set("k", "super-secret")

    assert "super-secret" not in (tmp_path / "s.json").read_text(encoding="utf-8")
    assert store.get("k") == "super-secret"
    assert store.delete("k") and store.get("k") is None


def test_catalog_loads_and_lifecycle(env):
    secrets, audit, connectors, tmp_path = env
    assert {"google-workspace", "github", "spotify", "canva", "higgsfield"} <= {
        item["id"] for item in connectors.view()}
    assert connectors.status("github") == "disconnected"

    connectors.authenticate("github", "tok-123")
    connectors.grant("github", ["repo.read"])
    assert connectors.status("github") == "connected"
    assert connectors.tool_ready("github.search_repositories") == (True, "")
    assert connectors.tool_ready("github.create_issue")[0] is False

    with pytest.raises(ConnectorError):
        connectors.grant("github", ["admin.everything"])

    connectors.revoke("github")
    assert connectors.status("github") == "disconnected"
    assert secrets.get("connector:github") is None
    assert connectors.scopes.granted("github") == set()


def test_scopes_persist_and_calls_are_audited(env):
    secrets, audit, connectors, tmp_path = env
    connectors.set_invoker("github", lambda tool, args: {"tool": tool, "args": args})
    connectors.authenticate("github", "tok")
    connectors.grant("github", ["repo.read"])

    assert connectors.call_tool("github.search_repositories", {"q": "x", "token": "t"})["tool"]
    with pytest.raises(ConnectorError):
        connectors.call_tool("github.create_issue", {})

    outcomes = [(e["tool"], e["outcome"]) for e in audit.entries()
                if e["tool"].startswith("github.")]
    assert outcomes == [("github.search_repositories", "ok"), ("github.create_issue", "denied")]
    assert audit.entries()[-1]["arguments"] == {}
    assert any(e["arguments"].get("token") == "[REDACTED]" for e in audit.entries())

    again = ConnectorRegistry(tmp_path / "connectors.json", secrets, audit)
    assert again.scopes.granted("github") == {"repo.read"}


def test_descriptor_rejects_undeclared_scope():
    with pytest.raises(ConnectorError):
        ConnectorDescriptor.from_dict({
            "id": "x", "name": "X", "type": "remote-mcp", "transport": "sse",
            "auth": "none", "scopes": [], "tool_refs": {"x.t": "missing"}})


def test_frontmatter_folded_description():
    meta, body = parse_frontmatter("---\nname: a\ndescription: >\n  uno\n  due\n---\n# Corpo\n")

    assert meta["description"] == "uno due"
    assert body == "# Corpo"


def _skills(tmp_path, audit):
    return SkillRegistry(ROOT / "skills", tmp_path / "skills.json", audit)


def test_skill_needs_approval_then_activates_with_connector_check(env):
    secrets, audit, connectors, tmp_path = env
    skills = _skills(tmp_path, audit)
    skills.load()

    assert skills.get("google-workspace-briefing").status == "review_required"
    assert skills.metadata() == []
    with pytest.raises(SkillError):
        skills.activate("google-workspace-briefing", connectors)

    skills.approve("google-workspace-briefing", reviewer="utente")
    activation = skills.activate("google-workspace-briefing", connectors)
    assert not activation.ready and "gmail.search" in activation.missing[0]
    assert "Procedura" in activation.body

    connectors.authenticate("google-workspace", "tok")
    connectors.grant("google-workspace", ["gmail.read", "calendar.read", "drive.read"])
    assert skills.activate("google-workspace-briefing", connectors).ready


def test_permission_change_and_revoke_force_review(env):
    secrets, audit, connectors, tmp_path = env
    skills = _skills(tmp_path, audit)
    skills.load()
    skills.approve("google-workspace-briefing", reviewer="utente")

    reloaded = _skills(tmp_path, audit)
    reloaded.load()
    assert reloaded.get("google-workspace-briefing").status == "active"

    connectors.on_revoke(lambda cid: reloaded.disable_for_connector(cid, connectors))
    connectors.authenticate("google-workspace", "tok")
    connectors.revoke("google-workspace")
    assert reloaded.get("google-workspace-briefing").status == "review_required"

    again = _skills(tmp_path, audit)
    again.load()
    assert again.get("google-workspace-briefing").status == "review_required"


def test_reference_cannot_escape_skill_folder(env):
    secrets, audit, connectors, tmp_path = env
    skills = _skills(tmp_path, audit)
    skills.load()

    with pytest.raises(SkillError):
        skills.read_reference("google-workspace-briefing", "../../main.py")


def test_router_picks_skill_and_intent(env):
    secrets, audit, connectors, tmp_path = env
    skills = _skills(tmp_path, audit)
    skills.load()
    skills.approve("google-workspace-briefing", reviewer="utente")
    router = SkillRouter(skills, connectors)

    route, activation = router.prepare("Jarvis, cosa ho oggi?")
    assert route.skill == "google-workspace-briefing" and activation is not None
    assert router.route("raccontami una barzelletta").skill is None
    assert classify_intent("trova il bug nel codice") == "technical"
    assert classify_intent("scrivi una poesia") == "creative"

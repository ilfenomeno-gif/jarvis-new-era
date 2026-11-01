"""
Declarative skills (``skills/<name>/SKILL.md``) with progressive disclosure.

Level 1: only name + description are loaded at startup.
Level 2: the SKILL.md body is read when the skill is selected.
Level 3: reference files are read on demand, never outside the skill folder.

A skill is a versioned artefact: it only runs when ``active`` *and* its
approved snapshot (tool_refs + risk_class) matches what is on disk. Any change
that touches permissions puts it back to ``review_required``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from core.audit_log import AuditLog
from core.connectors import ConnectorRegistry

STATUSES = ("draft", "active", "update_requested", "review_required", "archived")
RISK_CLASSES = ("read", "write", "destructive")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class SkillError(Exception):
    pass


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal YAML subset: ``key: value`` and folded ``key: >`` blocks."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("SKILL.md must start with a '---' frontmatter block.")
    meta: dict[str, str] = {}
    key = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            body = "\n".join(lines[index + 1:]).strip("\n")
            return {k: v.strip() for k, v in meta.items()}, body
        if line[:1] in (" ", "\t") and key:
            meta[key] += " " + line.strip()
            continue
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not match:
            continue
        key = match.group(1)
        value = match.group(2).strip()
        meta[key] = "" if value in (">", "|") else value
    raise SkillError("Frontmatter block is not closed with '---'.")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    triggers: list[str] = field(default_factory=list)
    tool_refs: list[str] = field(default_factory=list)
    risk_class: str = "read"
    status: str = "draft"
    reason: str = ""

    def snapshot(self) -> dict:
        return {"tool_refs": sorted(self.tool_refs), "risk_class": self.risk_class}


@dataclass
class Activation:
    skill: str
    body: str
    missing: list[str]
    ready: bool


class SkillRegistry:
    def __init__(self, skills_dir: Path, state_path: Path, audit: AuditLog) -> None:
        self._dir = Path(skills_dir)
        self._state_path = Path(state_path)
        self._audit = audit
        self._skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}
        self._approved: dict[str, dict] = self._read_state().get("approved", {})
        self._forced: dict[str, str] = self._read_state().get("forced", {})

    def _read_state(self) -> dict:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps({"approved": self._approved, "forced": self._forced}, indent=2, sort_keys=True),
            encoding="utf-8")

    def load(self) -> None:
        """Level 1: read frontmatter only; bodies stay on disk."""
        self._skills.clear()
        self.errors.clear()
        if not self._dir.is_dir():
            return
        for folder in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            file = folder / "SKILL.md"
            if not file.is_file():
                continue
            try:
                meta, _ = parse_frontmatter(file.read_text(encoding="utf-8"))
                self._skills[meta.get("name", "")] = self._build(meta, folder)
            except (SkillError, OSError) as exc:
                self.errors[folder.name] = str(exc)

    def _build(self, meta: dict, folder: Path) -> Skill:
        name, description = meta.get("name", ""), meta.get("description", "")
        if not _NAME_RE.match(name) or name != folder.name:
            raise SkillError(f"name {name!r} must be kebab-case and match its folder")
        if not description:
            raise SkillError("description is required")
        risk = meta.get("risk_class", "read")
        status = meta.get("status", "draft")
        if risk not in RISK_CLASSES:
            raise SkillError(f"risk_class {risk!r} invalid")
        if status not in STATUSES:
            raise SkillError(f"status {status!r} invalid")
        skill = Skill(name, description, folder, _split(meta.get("triggers", "")),
                      _split(meta.get("tool_refs", "")), risk, status)
        if name in self._forced:
            skill.status, skill.reason = "review_required", self._forced[name]
        elif status == "active" and self._approved.get(name) != skill.snapshot():
            skill.status = "review_required"
            skill.reason = "permissions not approved or changed since approval"
        return skill

    # -- governance --
    def diff(self, name: str) -> dict:
        skill = self.get(name)
        approved = self._approved.get(name, {"tool_refs": [], "risk_class": None})
        return {
            "added_tools": sorted(set(skill.tool_refs) - set(approved["tool_refs"])),
            "removed_tools": sorted(set(approved["tool_refs"]) - set(skill.tool_refs)),
            "risk_class": [approved["risk_class"], skill.risk_class],
        }

    def approve(self, name: str, reviewer: str) -> None:
        skill = self.get(name)
        if not reviewer:
            raise SkillError("A reviewer is required to approve a skill.")
        self._approved[name] = skill.snapshot()
        self._forced.pop(name, None)
        skill.status, skill.reason = "active", ""
        self._write_state()
        self._audit.record(tool="skill.approve", skill=name, outcome="ok", detail=reviewer)

    def disable_for_connector(self, connector_id: str, connectors: ConnectorRegistry) -> list[str]:
        affected = []
        for skill in self._skills.values():
            uses = False
            for ref in skill.tool_refs:
                try:
                    uses |= connectors.tool_scope(ref)[0].id == connector_id
                except Exception:
                    continue
            if uses:
                skill.status = "review_required"
                skill.reason = f"connector {connector_id} revoked"
                self._forced[skill.name] = skill.reason
                self._approved.pop(skill.name, None)
                affected.append(skill.name)
        if affected:
            self._write_state()
        return affected

    # -- access --
    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError:
            raise SkillError(f"Unknown skill {name!r}") from None

    def active(self) -> list[Skill]:
        return [s for s in self._skills.values() if s.status == "active"]

    def metadata(self) -> list[dict]:
        return [{"name": s.name, "description": s.description} for s in self.active()]

    def view(self) -> list[dict]:
        return [{"name": s.name, "status": s.status, "risk_class": s.risk_class,
                 "tool_refs": s.tool_refs, "reason": s.reason}
                for s in self._skills.values()]

    def read_body(self, name: str) -> str:
        """Level 2."""
        skill = self.get(name)
        return parse_frontmatter((skill.path / "SKILL.md").read_text(encoding="utf-8"))[1]

    def read_reference(self, name: str, relative: str) -> str:
        """Level 3, confined to the skill folder."""
        skill = self.get(name)
        root = skill.path.resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file():
            raise SkillError("Reference outside the skill folder or missing.")
        return target.read_text(encoding="utf-8")

    def activate(self, name: str, connectors: ConnectorRegistry | None = None) -> Activation:
        skill = self.get(name)
        if skill.status != "active":
            raise SkillError(f"Skill '{name}' is {skill.status}: {skill.reason or 'not approved'}")
        missing = []
        for ref in skill.tool_refs:
            if connectors is None:
                missing.append(f"{ref}: no connector registry")
                continue
            ok, reason = connectors.tool_ready(ref)
            if not ok:
                missing.append(f"{ref}: {reason}")
        self._audit.record(tool="skill.activate", skill=name, outcome="ok" if not missing else "blocked",
                           detail="; ".join(missing))
        return Activation(name, self.read_body(name), missing, not missing)

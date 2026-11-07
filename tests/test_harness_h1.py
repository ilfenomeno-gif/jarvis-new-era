from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.action_loader import ActionRecord, ActionRegistry, _validate
from core.harness.adapters import AgentLoopAdapter, ComputerLoopAdapter
from core.harness.config import load_harness_policy
from core.harness.observe import Tracer
from core.harness.policy import ApprovalPolicy
from core.harness.recovery import HarnessRecovery
from core.harness.runtime import HarnessRuntime
from core.harness.session import HarnessSession


class _FakeComputerLoop:
    def __init__(self):
        self.calls = []
        self.confirmation_calls = 0

    def run(self, goal, *, workspace=None):
        self.calls.append((goal, workspace))
        self.confirmation_calls += 1
        return SimpleNamespace(
            status="completed",
            summary="done",
            steps=[{"operation": "read_title", "success": True}],
            to_dict=lambda: {
                "status": "completed",
                "summary": "done",
                "steps": [{"operation": "read_title", "success": True}],
            },
        )


class _FakeAgentLoop:
    async def run(self, goal):
        return {"result": "success", "steps": 2, "goal": goal}


def _runtime(tmp_path, adapters):
    return HarnessRuntime(
        adapters=adapters,
        enabled=True,
        tracer=Tracer(tmp_path / "trace.jsonl"),
        recovery=HarnessRecovery(tmp_path / "recovery.jsonl"),
    )


def test_runtime_selects_computer_adapter_and_preserves_single_loop_gate(tmp_path):
    computer = _FakeComputerLoop()
    runtime = _runtime(tmp_path, {"computer_use_loop": ComputerLoopAdapter(computer)})
    session = HarnessSession(
        agent="computer_use_loop",
        goal="read the current page title",
        artifacts=[{"workspace": str(tmp_path)}],
        status="approved",
    )

    result = runtime.run(session)

    assert result.ok is True
    assert result.steps == [{"operation": "read_title", "success": True}]
    assert computer.calls == [("read the current page title", str(tmp_path))]
    assert computer.confirmation_calls == 1
    assert session.status == "completed"
    assert result.trace_id == session.trace_id


def test_agent_adapter_requires_approval_and_normalizes_agent_loop_result(tmp_path):
    adapter = AgentLoopAdapter(lambda _session: _FakeAgentLoop())
    runtime = _runtime(tmp_path, {"agent_loop": adapter})
    blocked = HarnessSession(agent="agent_loop", goal="test")
    approved = HarnessSession(agent="agent_loop", goal="test", status="approved")

    blocked_result = runtime.run(blocked)
    result = runtime.run(approved)

    assert blocked_result.ok is False
    assert blocked_result.error == "Explicit approval is required."
    assert result.ok is True
    assert result.steps == [{"count": 2}]
    assert result.trace_id == approved.trace_id


def test_missing_or_invalid_risk_is_fail_closed_and_registry_declaration_is_respected():
    policy = ApprovalPolicy(load_harness_policy())
    session = HarnessSession(agent="test", goal="test")
    registry = ActionRegistry(
        {
            "legacy_write": ActionRecord(name="legacy_write", risk_class="write"),
            "declared_destructive": ActionRecord(
                name="declared_destructive",
                risk_class="destructive",
                risk_class_declared=True,
            ),
            "declared_read": ActionRecord(
                name="declared_read",
                risk_class="read",
                risk_class_declared=True,
            ),
        },
        logger=lambda _message: None,
    )

    missing = policy.evaluate({"name": "legacy_write"}, {}, session, registry=registry)
    declared = policy.evaluate({"name": "declared_read"}, {}, session, registry=registry)
    mismatch = policy.evaluate(
        {"name": "declared_destructive", "risk_class": "read"},
        {},
        session,
        registry=registry,
    )
    invalid = policy.evaluate({"name": "plugin", "risk_class": "unknown"}, {}, session)
    overridden = policy.evaluate(
        {
            "name": "file_controller",
            "capabilities": {
                "effects": ["destructive"],
                "sensitive_arguments": [],
                "requires_confirmation": True,
            },
        },
        {},
        session,
    )

    assert (missing.risk_level, missing.requires_confirm) == ("destructive", True)
    assert (declared.risk_level, declared.requires_confirm) == ("read", False)
    assert (mismatch.risk_level, mismatch.requires_confirm) == ("destructive", True)
    assert (invalid.risk_level, invalid.requires_confirm) == ("destructive", True)
    assert (overridden.risk_level, overridden.requires_confirm) == ("destructive", True)


def test_action_registry_tracks_whether_risk_was_explicitly_declared():
    legacy = _validate(
        SimpleNamespace(TOOL={
            "name": "legacy_tool",
            "description": "Legacy tool",
            "parameters": {"type": "OBJECT", "properties": {}},
            "handler": lambda **_kwargs: "ok",
        }),
        "legacy_tool.py",
    )
    declared = _validate(
        SimpleNamespace(
            TOOL={
                "name": "read_tool",
                "description": "Read tool",
                "parameters": {"type": "OBJECT", "properties": {}},
                "risk_class": "read",
                "handler": lambda **_kwargs: "ok",
            }
        ),
        "read_tool.py",
    )
    registry = ActionRegistry(
        {record.name: record for record in (legacy, declared)},
        logger=lambda _message: None,
    )

    assert registry.risk_class_declared("legacy_tool") is False
    assert registry.risk_class_declared("read_tool") is True


def test_recovery_journal_persists_only_whitelisted_metadata(tmp_path):
    path = tmp_path / "harness.jsonl"
    recovery = HarnessRecovery(path)
    session = HarnessSession(
        agent="supervisor",
        goal="PRIVATE_USER_GOAL",
        history=[
            {"role": "user", "content": "PRIVATE_PROMPT"},
            {"role": "assistant", "content": "PRIVATE_RESPONSE"},
        ],
        artifacts=[{"name": "PRIVATE_FILENAME", "type": "report", "size": 20}],
        usage={"input_tokens": 4, "output_tokens": 5, "raw_prompt": "PRIVATE_USAGE"},
        status="completed",
    )

    recovery.checkpoint(session)
    journal = path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in journal.splitlines()]
    restored = recovery.restore(session.id)

    assert "PRIVATE_USER_GOAL" not in journal
    assert "PRIVATE_PROMPT" not in journal
    assert "PRIVATE_RESPONSE" not in journal
    assert "PRIVATE_FILENAME" not in journal
    assert "PRIVATE_USAGE" not in journal
    assert records[0]["goal_sha256"]
    assert records[0]["history"][0]["content_sha256"]
    assert records[0]["artifacts"] == [{"type": "report", "size": 20}]
    assert records[0]["usage"] == {"input_tokens": 4, "output_tokens": 5}
    assert restored.goal == ""
    assert restored.history == []
    assert restored.status == "recovered_metadata_only"


def test_resume_reports_metadata_only_checkpoint_instead_of_replaying(tmp_path):
    recovery = HarnessRecovery(tmp_path / "harness.jsonl")
    session = HarnessSession(agent="supervisor", goal="private goal")
    recovery.checkpoint(session)
    runtime = HarnessRuntime(
        enabled=True,
        recovery=recovery,
        tracer=Tracer(tmp_path / "trace.jsonl"),
    )

    result = runtime.resume(session.id)

    assert result.ok is False
    assert "metadata only" in result.error


def test_harness_is_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("JARVIS_HARNESS", raising=False)
    runtime = HarnessRuntime(recovery=HarnessRecovery(tmp_path / "harness.jsonl"))

    with pytest.raises(RuntimeError, match="JARVIS_HARNESS=1"):
        runtime.run(HarnessSession(agent="missing", goal="test"))

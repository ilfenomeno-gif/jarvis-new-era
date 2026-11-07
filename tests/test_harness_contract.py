from __future__ import annotations

import ast
import json
from pathlib import Path

from core.harness.config import load_harness_policy
from core.harness.context import ContextAssembler
from core.harness.eval import EvalCase, EvalResult
from core.harness.observe import Tracer
from core.harness.policy import ApprovalPolicy
from core.harness.runtime import HarnessResult
from core.harness.session import HarnessSession

ROOT = Path(__file__).resolve().parents[1]


def test_harness_session_round_trip():
    original = HarnessSession(
        agent="supervisor",
        goal="test",
        history=[{"role": "user", "content": "hello"}],
        artifacts=[{"name": "report"}],
        usage={"tokens": 7},
        status="running",
    )
    restored = HarnessSession.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_harness_result_serializes_trace_and_usage():
    result = HarnessResult(
        ok=True,
        trace_id="trace-123",
        usage={"input_tokens": 10, "output_tokens": 5},
    ).to_dict()
    assert result["trace_id"] == "trace-123"
    assert result["usage"]["input_tokens"] == 10


def test_approval_policy_risk_decisions_and_denylist():
    loaded_policy = load_harness_policy()
    assert loaded_policy["version"] == 1
    policy = ApprovalPolicy({
        **loaded_policy,
        "policy": {
            **loaded_policy["policy"],
            "denylist_patterns": [r"rm\s+-rf\s+/"],
        },
    })
    session = HarnessSession(agent="test", goal="test")
    read = policy.evaluate({"name": "read", "risk_class": "read"}, {}, session)
    write = policy.evaluate({"name": "write", "risk_class": "write"}, {}, session)
    destructive = policy.evaluate(
        {"name": "delete", "risk_class": "destructive"},
        {"command": "delete selected item"},
        session,
    )
    denied = policy.evaluate(
        {"name": "terminal", "risk_class": "destructive"},
        {"command": "rm -rf /"},
        session,
    )
    assert (read.allowed, read.requires_confirm) == (True, False)
    assert (write.allowed, write.requires_confirm) == (True, True)
    assert (destructive.allowed, destructive.requires_confirm) == (True, True)
    assert denied.allowed is False


def test_context_assembler_includes_system_latest_history_and_compaction():
    assembler = ContextAssembler(
        max_context_tokens=10,
        compaction_ratio=0.5,
        max_history_messages=2,
        system_prompt="system",
    )
    session = HarnessSession(
        agent="test",
        goal="latest",
        history=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "middle"},
            {"role": "user", "content": "latest"},
        ],
    )
    messages = assembler.build(session, {"system_prompt": "policy system"})
    assert messages[0] == {"role": "system", "content": "policy system"}
    assert messages[-1] == {"role": "user", "content": "latest"}
    assert len(messages) == 3
    assert assembler.should_compact(session)


def test_tracer_journals_metadata_only(tmp_path):
    path = tmp_path / "harness_runs.jsonl"
    tracer = Tracer(path)
    trace_id = tracer.start_run(agent="supervisor")
    span_id = tracer.start_span("tool", tool="file_controller")
    tracer.event(
        "tool_result",
        tool="file_controller",
        outcome="ok",
        prompt="private prompt",
        response="private answer",
        tokens=12,
    )
    tracer.end_span(span_id, ok=True, tool="file_controller")
    tracer.end_run(ok=True, tokens=12)
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert all(record["trace_id"] == trace_id for record in records)
    assert any(record.get("span_id") == span_id for record in records)
    journal = path.read_text(encoding="utf-8")
    assert "private prompt" not in journal
    assert "private answer" not in journal


def test_eval_case_and_result_round_trip():
    case = EvalCase("case-1", {"question": "hello"}, "hi", {"suite": "smoke"})
    result = EvalResult("case-1", True, score=1.0, trace_id="trace-1")
    assert EvalCase.from_dict(case.to_dict()) == case
    assert EvalResult.from_dict(result.to_dict()) == result


def test_harness_contract_does_not_import_application_layers():
    forbidden = {"actions", "agents", "main", "ui"}
    package = ROOT / "core" / "harness"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            else:
                continue
            assert not forbidden.intersection(names), f"forbidden import in {path}"

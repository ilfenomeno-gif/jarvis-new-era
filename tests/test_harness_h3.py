from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.action_loader import ActionRecord, ActionRegistry, _validate, strip_meta
from core.harness.api_contract import list_capabilities
from core.harness.capabilities import (
    Capability,
    ToolCapabilities,
    validate_arguments,
)
from core.harness.eval import EvalCase, run_eval
from core.harness.eval_cli import main as eval_main
from core.harness.judge import run_configured_eval
from core.harness.policy import ApprovalPolicy
from core.harness.recovery import HarnessRecovery
from core.harness.session import HarnessSession


def _registry(name: str, capability: ToolCapabilities | None = None, *, declared=False):
    record = ActionRecord(
        name=name,
        risk_class="read",
        risk_class_declared=True,
        capabilities=capability,
        capabilities_declared=declared,
    )
    return ActionRegistry({name: record}, logger=lambda _message: None)


def test_typed_capabilities_override_risk_fallback_and_sensitive_arguments_confirm():
    policy = ApprovalPolicy({
        "default": {"read": "auto", "write": "confirm", "destructive": "confirm"},
    })
    capability = ToolCapabilities.from_value({
        "effects": ["read"],
        "sensitive_arguments": ["path"],
        "requires_confirmation": False,
    })

    safe = policy.evaluate(
        {"name": "reader", "risk_class": "destructive", "capabilities": capability.to_dict()},
        {},
        None,
    )
    sensitive = policy.evaluate(
        {"name": "reader", "capabilities": capability.to_dict()},
        {"path": "private.txt"},
        None,
    )

    assert safe.risk_level == "read"
    assert safe.requires_confirm is False
    assert sensitive.requires_confirm is True


def test_capability_invalid_missing_and_registry_mismatch_fail_closed():
    policy = ApprovalPolicy()
    invalid = policy.evaluate(
        {
            "name": "tool",
            "capabilities": {
                "effects": ["unknown"],
                "sensitive_arguments": [],
                "requires_confirmation": False,
            },
        },
        {},
        None,
    )
    absent = policy.evaluate({"name": "tool"}, {}, None)
    declared = ToolCapabilities.from_value({
        "effects": ["read"],
        "sensitive_arguments": [],
        "requires_confirmation": False,
    })
    mismatch = policy.evaluate(
        {
            "name": "tool",
            "capabilities": {
                "effects": ["destructive"],
                "sensitive_arguments": [],
                "requires_confirmation": True,
            },
        },
        {},
        None,
        registry=_registry("tool", declared, declared=True),
    )

    assert invalid.allowed is False and invalid.risk_level == "destructive"
    assert absent.allowed is True and absent.requires_confirm is True
    assert mismatch.allowed is False


def test_incomplete_typed_capability_fails_closed():
    policy = ApprovalPolicy()
    schema = {"type": "OBJECT", "properties": {}}
    incomplete_contracts = (
        {"risk_class": "read"},
        {"effects": ["read"]},
    )

    for contract in incomplete_contracts:
        decision = policy.evaluate(
            {
                "name": "typed",
                "parameters": schema,
                "capability": contract,
            },
            {},
            None,
        )
        assert decision.allowed is False
        assert decision.risk_level == "destructive"


def test_action_registry_parses_capability_contract_and_tracks_invalid_contract():
    valid = _validate(
        SimpleNamespace(TOOL={
            "name": "typed",
            "description": "Typed tool",
            "parameters": {"type": "OBJECT", "properties": {}},
            "capabilities": {
                "effects": ["read"],
                "sensitive_arguments": [],
                "requires_confirmation": False,
            },
            "handler": lambda **_kwargs: "ok",
        }),
        "typed.py",
    )
    invalid = _validate(
        SimpleNamespace(TOOL={
            "name": "invalid",
            "description": "Invalid tool",
            "parameters": {"type": "OBJECT", "properties": {}},
            "capabilities": {"effects": ["unknown"], "requires_confirmation": False},
            "handler": lambda **_kwargs: "ok",
        }),
        "invalid.py",
    )
    registry = ActionRegistry(
        {record.name: record for record in (valid, invalid)},
        logger=lambda _message: None,
    )

    assert valid.valid and registry.capabilities_declared("typed")
    assert registry.capabilities("typed").risk_level == "read"
    assert registry.get_capability("typed").risk_class == "read"
    assert registry.capabilities_declared("invalid")
    assert registry.capabilities_error("invalid")
    assert registry.get_capability("invalid") is None
    assert registry.capability_error("invalid")
    assert strip_meta([{"name": "typed", "capabilities": {"effects": ["read"]}}]) == [
        {"name": "typed"}
    ]


def test_legacy_action_default_risk_stays_write_in_capability_contract():
    record = _validate(
        SimpleNamespace(
            TOOL={
                "name": "legacy_tool",
                "description": "Handle local task.",
                "parameters": {"type": "OBJECT", "properties": {}},
                "handler": lambda **_kwargs: None,
            }
        ),
        "legacy_tool.py",
    )

    assert record.valid
    assert record.risk_class == "write"
    assert record.risk_class_declared is False
    assert record.capability_contract.risk_class == "write"
    assert record.capability_contract.requires_confirmation is True


def test_capability_round_trip_and_six_existing_high_risk_tools():
    legacy_contract = {
        "file_controller": ["read", "write", "destructive"],
        "desktop_control": ["write", "destructive"],
        "proxy_launcher": ["destructive"],
        "vscode_control": ["write", "destructive"],
        "file_processor": ["write", "destructive"],
        "shutdown_jarvis": ["destructive"],
    }
    for name, old_effects in legacy_contract.items():
        capability = Capability.from_tool_dict({
            "name": name,
            "description": f"{name} action",
            "parameters": {
                "type": "OBJECT",
                "properties": {"path": {"type": "STRING"}},
                "required": ["path"],
            },
            "capabilities": {
                "effects": old_effects,
                "sensitive_arguments": ["path"],
                "requires_confirmation": True,
            },
        })
        restored = Capability.from_tool_dict(capability.to_dict())
        assert restored == capability
        assert restored.risk_class == "destructive"
        assert restored.requires_confirmation is True
        assert restored.effects


def test_capability_argument_validation_supports_schema_subset():
    capability = Capability.from_tool_dict({
        "name": "lookup",
        "description": "Read a record.",
        "risk_class": "read",
        "effects": ["read", "filesystem"],
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "record_id": {"type": "STRING", "pattern": "^[a-z0-9-]+$"},
                "format": {"type": "STRING", "enum": ["json", "text"]},
            },
            "required": ["record_id"],
        },
    })

    assert validate_arguments(capability, {"record_id": "item-42", "format": "json"}).valid
    invalid = validate_arguments(capability, {"record_id": "BAD ID", "format": "xml"})
    assert invalid.valid is False
    assert any("pattern" in error for error in invalid.errors)
    assert any("enum" in error for error in invalid.errors)
    assert any("required" in error for error in validate_arguments(capability, {}).errors)


def test_approval_policy_prefers_capability_and_falls_back_to_declared_risk():
    policy = ApprovalPolicy({
        "default": {"read": "auto", "write": "confirm", "destructive": "confirm"},
    })
    capability = Capability.from_tool_dict({
        "name": "safe_reader",
        "description": "Read a file.",
        "risk_class": "read",
        "effects": ["read", "filesystem"],
        "requires_confirmation": False,
        "parameters": {"type": "OBJECT", "properties": {}},
    })
    capability_registry = ActionRegistry(
        {
            "safe_reader": ActionRecord(
                name="safe_reader",
                capability_contract=capability,
                risk_class="destructive",
                risk_class_declared=True,
            )
        },
        logger=lambda _message: None,
    )
    capability_decision = policy.evaluate(
        {"name": "safe_reader"}, {}, None, registry=capability_registry
    )
    fallback_registry = ActionRegistry(
        {
            "legacy_reader": ActionRecord(
                name="legacy_reader",
                risk_class="read",
                risk_class_declared=True,
            )
        },
        logger=lambda _message: None,
    )
    fallback_decision = policy.evaluate(
        {"name": "legacy_reader"}, {}, None, registry=fallback_registry
    )
    invalid_registry = ActionRegistry(
        {
            "invalid": ActionRecord(
                name="invalid",
                capability_contract=Capability(
                    name="invalid",
                    description="invalid test contract",
                    version="1",
                    parameters_schema={"type": "object"},
                    effects=[],
                    risk_class="read",
                    requires_confirmation=False,
                    scope="test",
                ),
            )
        },
        logger=lambda _message: None,
    )
    invalid_decision = policy.evaluate(
        {"name": "invalid"}, {}, None, registry=invalid_registry
    )

    assert (capability_decision.risk_level, capability_decision.requires_confirm) == (
        "read",
        False,
    )
    assert (fallback_decision.risk_level, fallback_decision.requires_confirm) == (
        "read",
        False,
    )
    assert invalid_decision.allowed is False
    assert invalid_decision.risk_level == "destructive"


def test_list_capabilities_returns_versioned_sorted_contract():
    registry = ActionRegistry(
        {
            name: ActionRecord(
                name=name,
                capability_contract=Capability.from_tool_dict({
                    "name": name,
                    "description": "Read local data.",
                    "risk_class": "read",
                    "effects": ["read"],
                    "requires_confirmation": False,
                    "parameters": {"type": "OBJECT", "properties": {}},
                }),
            )
            for name in ("z_reader", "a_reader")
        },
        logger=lambda _message: None,
    )

    result = list_capabilities(registry)

    assert result["contractVersion"] == 1
    assert [item["name"] for item in result["capabilities"]] == ["a_reader", "z_reader"]
    assert all(item["parameters_schema"]["type"] == "object" for item in result["capabilities"])


def test_rule_based_eval_passes_and_fails_local_rules():
    cases = [
        EvalCase(
            "substring-pass",
            "Local evaluation passed.",
            expected="passed",
            metadata={"rule": "substring"},
        ),
        EvalCase(
            "substring-fail",
            "Local evaluation passed.",
            expected="missing",
            metadata={"rule": "substring"},
        ),
        EvalCase(
            "regex-fail",
            "status: pending",
            expected=r"^status: ready$",
            metadata={"rule": "regex"},
        ),
        EvalCase(
            "json-fail",
            "{not json}",
            metadata={"rule": "json"},
        ),
    ]

    results = run_eval(cases)

    assert [result.ok for result in results] == [True, False, False, False]


def test_harness_computer_adapter_validates_real_tool_arguments(tmp_path):
    from core.harness.adapters import ComputerLoopAdapter
    from core.harness.runtime import HarnessRuntime

    record = ActionRecord(
        name="computer_use_loop",
        risk_class="write",
        risk_class_declared=True,
        capability_contract=Capability.from_tool_dict({
            "name": "computer_use_loop",
            "description": "Run a bounded computer-use goal.",
            "risk_class": "write",
            "effects": ["desktop", "subprocess"],
            "requires_confirmation": True,
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "goal": {"type": "STRING"},
                    "workspace": {"type": "STRING"},
                },
                "required": ["goal"],
            },
        }),
    )
    registry = ActionRegistry({"computer_use_loop": record}, logger=lambda _message: None)
    calls = []

    class Loop:
        def run(self, goal, *, workspace=None):
            calls.append((goal, workspace))
            return {"status": "completed", "steps": []}

    runtime = HarnessRuntime(
        adapters={"computer_use_loop": ComputerLoopAdapter(Loop())},
        enabled=True,
        action_registry=registry,
    )
    session = HarnessSession(
        agent="computer_use_loop",
        goal="Read the visible screen",
        artifacts=[{"workspace": str(tmp_path)}],
        status="approved",
    )

    result = runtime.run(session)

    assert result.ok is True
    assert calls == [("Read the visible screen", str(tmp_path))]


def test_capabilities_endpoint_is_opt_in_and_requires_dashboard_token(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from dashboard.server import DashboardServer

    registry = _registry("read_tool")
    server = DashboardServer.__new__(DashboardServer)
    server._capability_registry = registry
    server._tokens = {"live-token": time.time()}
    server._token_keys = {}
    monkeypatch.delenv("JARVIS_HARNESS", raising=False)
    monkeypatch.delenv("JARVIS_HARNESS_API", raising=False)
    assert TestClient(server._build_app()).get("/capabilities").status_code == 404
    monkeypatch.setenv("JARVIS_HARNESS", "1")
    monkeypatch.setenv("JARVIS_HARNESS_API", "1")
    client = TestClient(server._build_app())

    assert client.get("/capabilities").status_code == 401
    response = client.get(
        "/capabilities",
        headers={"Authorization": "Bearer live-token"},
    )
    assert response.status_code == 200
    assert response.json()["contractVersion"] == 1


def test_remote_pairing_manual_key_length_matches_login_form():
    from dashboard.server import DashboardServer

    server = DashboardServer.__new__(DashboardServer)
    server._pending_keys = {}
    key = server.new_key()
    login_html = (
        Path(__file__).resolve().parents[1]
        / "dashboard"
        / "static"
        / "login.html"
    ).read_text(encoding="utf-8")

    assert len(key) == 8
    assert 'maxlength="8"' in login_html
    assert "inp.value.length === 8" in login_html
    assert "key.length < 8" in login_html


def test_llm_judge_is_explicit_h4_stub(monkeypatch):
    monkeypatch.setenv("JARVIS_HARNESS_JUDGE_LLM", "1")
    adapter = SimpleNamespace(chat=lambda *_args, **_kwargs: pytest.fail("stub must not call LLM"))
    with pytest.raises(NotImplementedError, match="deferred to H4"):
        run_configured_eval(
            [EvalCase("llm-stub", "synthetic")],
            judge_mode="llm",
            llm=adapter,
        )


def test_replay_needs_environment_and_explicit_consent_and_checks_integrity(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("JARVIS_HARNESS_REPLAY", "1")
    recovery = HarnessRecovery(tmp_path / "replay.jsonl")
    session = HarnessSession(
        agent="agent_loop",
        goal="private goal",
        history=[
            {"role": "user", "content": "private prompt", "ignored": "not persisted"},
            {"role": "assistant", "content": "private answer password=topsecret"},
        ],
    )

    recovery.checkpoint(session, replay_consent=True)
    refused = recovery.restore(session.id)
    restored = recovery.restore(session.id, replay_consent=True)
    assert refused.goal == "" and refused.history == []
    assert "explicit consent" in refused.recovery_reason
    assert restored.goal == session.goal
    assert restored.history == [
        {"role": "user", "content": "private prompt"},
        {"role": "assistant", "content": "private answer password=[REDACTED]"},
    ]
    assert restored.status == "recovered_replay_ready"

    lines = recovery.journal_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[-1])
    record["replay"]["goal"] = "tampered"
    recovery.journal_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    tampered = recovery.restore(session.id, replay_consent=True)
    assert tampered.goal == ""
    assert tampered.status == "recovered_metadata_only"

    monkeypatch.delenv("JARVIS_HARNESS_REPLAY")
    recovery.checkpoint(session, replay_consent=True)
    refused_by_flag = recovery.restore(session.id, replay_consent=True)
    assert refused_by_flag.goal == ""
    assert refused_by_flag.status == "recovered_metadata_only"


def test_rule_based_judge_runs_through_eval_and_documented_suite(tmp_path):
    cases = [
        EvalCase("exact", "same", expected="same"),
        EvalCase("contains", "local harness", expected="local", metadata={"rule": "contains"}),
    ]
    results = run_configured_eval(cases)
    assert [result.ok for result in results] == [True, True]

    suite = tmp_path / "suite.yaml"
    suite.write_text(
        "version: 1\ncases:\n  - id: cli\n    input: ok\n    expected: ok\n",
        encoding="utf-8",
    )
    assert eval_main(["--suite", str(suite)]) == 0


def test_llm_judge_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("JARVIS_HARNESS_LLM_JUDGE", raising=False)
    with pytest.raises(RuntimeError, match="JARVIS_HARNESS_LLM_JUDGE=1"):
        run_configured_eval([EvalCase("llm", "actual", expected="expected")], judge_mode="llm")

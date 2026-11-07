import json

import pytest

from core.audit_log import AuditLog
from core.computer_loop import ComputerLoop
from core.memory_store import MemoryStore
from core.terminal_agent import TerminalAgent


def _loop(tmp_path, planner, **kwargs):
    database = tmp_path / "memory.sqlite3"
    return ComputerLoop(
        terminal_agent=TerminalAgent(database_path=tmp_path / "terminal.sqlite3"),
        memory_store=MemoryStore(database),
        audit_log=AuditLog(tmp_path / "audit.jsonl"),
        planner=planner,
        **kwargs,
    )


def _step(command, *, expected_output=None):
    verify = {"exit_code": 0}
    if expected_output is not None:
        verify["stdout_contains"] = expected_output
    return {
        "description": f"Run {command}",
        "action": {"type": "terminal", "operation": "command", "command": command},
        "verify": verify,
    }


def test_computer_loop_executes_captures_verifies_and_audits(tmp_path):
    loop = _loop(tmp_path, lambda *_: [_step("echo hello", expected_output="hello")])
    try:
        result = loop.run("Print hello", workspace=tmp_path)
        assert result.status == "completed"
        assert result.steps[0].stdout.strip() == "hello"
        assert result.steps[0].returncode == 0
        assert result.steps[0].verification == "verified"

        entries = AuditLog(tmp_path / "audit.jsonl").entries()
        assert any(entry["tool"] == "computer_loop" for entry in entries)
        memory = MemoryStore(tmp_path / "memory.sqlite3")
        try:
            events = memory.list_events("computer-loop:")
        finally:
            memory.close()
        assert len(events) == 1
        assert events[0]["event_type"] == "action_succeeded"
    finally:
        loop.close()


def test_computer_loop_replans_after_failed_verification(tmp_path):
    plans = iter(
        [
            [_step("echo first", expected_output="not present")],
            [_step("echo recovered", expected_output="recovered")],
        ]
    )
    planning_context = []

    def planner(goal, history, workspace):
        planning_context.append((goal, list(history), workspace))
        return next(plans)

    loop = _loop(tmp_path, planner, max_retries=1)
    try:
        result = loop.run("Recover the failed command", workspace=tmp_path)
        assert result.status == "completed"
        assert result.attempts == 2
        assert result.retry_count == 1
        assert any(step.attempt == 1 and not step.success for step in result.steps)
        assert result.steps[-1].attempt == 2
        assert planning_context[1][1][0]["success"] is False
    finally:
        loop.close()


def test_computer_loop_caps_retries_and_suppresses_repeated_failed_action(tmp_path):
    calls = []

    def planner(_goal, _history, _workspace):
        calls.append("planned")
        return [_step("echo same", expected_output="never")]

    loop = _loop(tmp_path, planner, max_retries=2)
    try:
        result = loop.run("Do not loop forever", workspace=tmp_path)
        assert result.status == "failed"
        assert result.attempts == 3
        assert result.retry_count == 2
        assert len(calls) == 3
        assert sum(step.returncode == 0 for step in result.steps) == 1
        assert "suppressed" in result.steps[-1].stderr
    finally:
        loop.close()


def test_computer_loop_rejects_workspace_escape(tmp_path):
    loop = _loop(
        tmp_path,
        lambda *_: [
            {
                "description": "Copy a file outside the workspace",
                "action": {
                    "type": "terminal",
                    "operation": "copy_file",
                    "source": "missing.py",
                    "destination": "../outside.py",
                },
            }
        ],
        max_retries=0,
    )
    try:
        result = loop.run("Do not escape", workspace=tmp_path)
        assert result.status == "failed"
        assert "outside the approved workspace" in result.steps[0].stderr
    finally:
        loop.close()


def test_computer_loop_captures_pytest_failure_output(tmp_path):
    (tmp_path / "test_failure.py").write_text(
        "def test_failure():\n    assert 1 == 2\n",
        encoding="utf-8",
    )
    loop = _loop(
        tmp_path,
        lambda *_: [
            {
                "description": "Run the failing test and report its result",
                "action": {
                    "type": "terminal",
                    "operation": "run_pytest",
                    "path": "test_failure.py",
                },
                "verify": {"exit_code": 1, "stdout_contains": "1 failed"},
            }
        ],
        timeout_seconds=30,
    )
    try:
        result = loop.run("Run one failing test", workspace=tmp_path)
        assert result.status == "completed"
        assert "1 failed" in result.steps[0].stdout
        assert result.steps[0].returncode == 1
        assert any(
            entry["arguments"].get("operation") == "run_pytest"
            for entry in AuditLog(tmp_path / "audit.jsonl").entries()
        )
    finally:
        loop.close()


def test_computer_loop_prefers_existing_pytest_ini(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("invalid toml\n", encoding="utf-8")
    (tmp_path / "test_success.py").write_text(
        "def test_success():\n    assert True\n",
        encoding="utf-8",
    )
    loop = _loop(
        tmp_path,
        lambda *_: [
            {
                "description": "Use the project's existing pytest config",
                "action": {
                    "type": "terminal",
                    "operation": "run_pytest",
                    "path": "test_success.py",
                },
                "verify": {"exit_code": 0, "stdout_contains": "1 passed"},
            }
        ],
    )
    try:
        result = loop.run("Run the configured project test", workspace=tmp_path)
        assert result.status == "completed"
        assert "1 passed" in result.steps[0].stdout
    finally:
        loop.close()


def test_computer_loop_requires_confirmation_for_policy_override(tmp_path):
    seen = []

    def requester(key, title, detail, callback, *, on_cancel):
        seen.append((key, title, detail))
        on_cancel()
        return "[CONFIRMATION_PENDING]"

    loop = _loop(
        tmp_path,
        lambda *_: [_step("python -c pass")],
        confirmation_requester=requester,
        max_retries=0,
    )
    try:
        result = loop.run("Run a command outside policy", workspace=tmp_path)
        assert result.status == "failed"
        assert result.steps[0].returncode == 125
        assert "declined" in result.steps[0].stderr
        assert len(seen) == 1
    finally:
        loop.close()


def test_computer_loop_validates_plan_shape_and_timeout():
    with pytest.raises(ValueError, match="max_retries"):
        ComputerLoop(max_retries=-1)
    with pytest.raises(ValueError, match="timeout_seconds"):
        ComputerLoop(timeout_seconds=0)

    with pytest.raises(ValueError, match="at most"):
        ComputerLoop(timeout_seconds=121)


def test_computer_loop_result_is_json_serializable(tmp_path):
    loop = _loop(tmp_path, lambda *_: [_step("echo json", expected_output="json")])
    try:
        result = loop.run("Return JSON-safe result", workspace=tmp_path)
        parsed = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
        assert parsed["status"] == "completed"
        assert parsed["steps"][0]["operation"] == "command"
    finally:
        loop.close()


def test_computer_loop_action_is_opt_in(monkeypatch):
    from actions.computer_loop import computer_loop

    monkeypatch.delenv("JARVIS_COMPUTER_LOOP", raising=False)
    assert "disabled" in computer_loop({"goal": "test"})

    monkeypatch.setenv("JARVIS_COMPUTER_LOOP", "1")
    with pytest.raises(RuntimeError, match="not initialized"):
        computer_loop({"goal": "test"})

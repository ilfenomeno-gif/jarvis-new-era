from __future__ import annotations

import threading

from core.harness import adapters
from core.harness.adapters import AgentLoopAdapter, ComputerLoopAdapter
from core.harness.eval import EvalCase, run_eval
from core.harness.observe import Tracer
from core.harness.recovery import HarnessRecovery
from core.harness.runtime import HarnessRuntime
from core.harness.session import HarnessSession


class _SingleStepComputerLoop:
    def __init__(self):
        self.interrupt_controller = None
        self.max_steps = None

    def run(self, goal, *, workspace=None, max_steps=None):
        self.max_steps = max_steps
        if self.interrupt_controller is not None:
            self.interrupt_controller.checkpoint(timeout=1)
        return {
            "status": "paused" if max_steps == 1 else "completed",
            "summary": goal,
            "steps": [{"operation": "read_title", "success": True}],
        }


class _SingleStepAgentLoop:
    async def run(self, goal):
        return {"result": "max_steps", "steps": 1, "reason": goal}


def _runtime(tmp_path, adapter):
    return HarnessRuntime(
        adapters={adapter.tool_spec["name"]: adapter},
        enabled=True,
        tracer=Tracer(tmp_path / "trace.jsonl"),
        recovery=HarnessRecovery(tmp_path / "recovery.jsonl"),
    )


def test_computer_adapter_single_step_limits_plan_to_one_action(tmp_path):
    loop = _SingleStepComputerLoop()
    runtime = _runtime(tmp_path, ComputerLoopAdapter(loop))
    session = HarnessSession(
        agent="computer_use_loop",
        goal="inspect page",
        status="approved",
    )

    result = runtime.step(session)

    assert result.ok is True
    assert loop.max_steps == 1
    assert result.steps == [{"operation": "read_title", "success": True}]
    assert session.status == "paused"


def test_agent_adapter_single_step_uses_existing_loop_with_one_step_limit(monkeypatch, tmp_path):
    calls = []

    def build_loop(session, *, single_step=False, interrupt_controller=None):
        calls.append((session.status, single_step, interrupt_controller is not None))
        return _SingleStepAgentLoop()

    monkeypatch.setattr(adapters, "_default_agent_loop", build_loop)
    runtime = _runtime(tmp_path, AgentLoopAdapter())
    session = HarnessSession(agent="agent_loop", goal="inspect screen", status="approved")

    result = runtime.step(session)

    assert result.ok is True
    assert result.steps == [{"count": 1, "status": "max_steps"}]
    assert calls == [("approved", True, True)]
    assert session.status == "paused"


def test_runtime_pause_and_stop_interrupt_active_computer_adapter(tmp_path):
    started = threading.Event()
    enter_checkpoint = threading.Event()
    checkpoint_blocked = threading.Event()

    class BlockingComputerLoop:
        interrupt_controller = None

        def run(self, goal, *, workspace=None, max_steps=None):
            del goal, workspace, max_steps
            started.set()
            enter_checkpoint.wait(timeout=2)
            checkpoint_blocked.set()
            try:
                self.interrupt_controller.checkpoint(timeout=2)
            except InterruptedError:
                return {"status": "stopped", "summary": "interrupted", "steps": []}
            return {"status": "completed", "summary": "resumed", "steps": []}

    loop = BlockingComputerLoop()
    runtime = _runtime(tmp_path, ComputerLoopAdapter(loop))
    session = HarnessSession(
        agent="computer_use_loop",
        goal="wait for interrupt",
        status="approved",
    )
    results = []
    worker = threading.Thread(target=lambda: results.append(runtime.run(session)))
    worker.start()

    assert started.wait(timeout=2)
    runtime.pause(session.id)
    enter_checkpoint.set()
    assert checkpoint_blocked.wait(timeout=2)
    runtime.stop(session.id)
    worker.join(timeout=3)

    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error == "stopped"


def test_eval_judge_is_optional_and_rule_based_without_network():
    cases = [EvalCase("local-rule", {"value": 2}, expected=2)]

    unjudged = run_eval(cases)
    judged = run_eval(cases, judge=lambda case: case.input["value"] == case.expected)

    assert unjudged[0].ok is None
    assert "No LLM judge configured" in unjudged[0].reason
    assert judged[0].ok is True


def test_metadata_only_checkpoint_refuses_replay_without_consent_or_plaintext(tmp_path):
    recovery = HarnessRecovery(tmp_path / "private-journal.jsonl")
    session = HarnessSession(
        agent="computer_use_loop",
        goal="PRIVATE_GOAL_FOR_REPLAY",
        history=[{"role": "user", "content": "PRIVATE_HISTORY"}],
    )
    recovery.checkpoint(session)
    restored = recovery.restore(session.id)
    contents = recovery.journal_path.read_text(encoding="utf-8")

    assert restored.goal == ""
    assert restored.history == []
    assert restored.status == "recovered_metadata_only"
    assert "PRIVATE_GOAL_FOR_REPLAY" not in contents
    assert "PRIVATE_HISTORY" not in contents

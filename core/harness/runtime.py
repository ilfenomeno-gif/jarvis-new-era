from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from core.harness.config import load_harness_policy
from core.harness.interrupt import InterruptController
from core.harness.observe import Tracer
from core.harness.policy import ApprovalPolicy
from core.harness.recovery import HarnessRecovery
from core.harness.session import HarnessSession


class LLM(Protocol):
    def chat(self, messages: list[dict[str, Any]], *, role: str = "chat", **kwargs: Any) -> str: ...

    def stream(self, messages: list[dict[str, Any]], *, role: str = "chat", **kwargs: Any) -> Any: ...

    def json(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        *,
        role: str = "json",
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def vision(
        self,
        messages: list[dict[str, Any]],
        images: list[Any],
        *,
        role: str = "vision",
        **kwargs: Any,
    ) -> str: ...


@dataclass
class HarnessResult:
    ok: bool
    steps: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HarnessRuntime:
    def __init__(
        self,
        llm: LLM | None = None,
        *,
        adapters: dict[str, Any] | None = None,
        approval_policy: ApprovalPolicy | None = None,
        tracer: Tracer | None = None,
        recovery: HarnessRecovery | None = None,
        enabled: bool | None = None,
        **components: Any,
    ) -> None:
        self.llm = llm
        self.adapters = dict(adapters or {})
        self.approval_policy = approval_policy or ApprovalPolicy(load_harness_policy())
        self.tracer = tracer or Tracer()
        self.recovery = recovery or HarnessRecovery()
        self.enabled = (
            os.environ.get("JARVIS_HARNESS", "0") == "1"
            if enabled is None
            else enabled
        )
        self.components = components
        self._active_adapters: dict[str, Any] = {}
        self._active_interrupts: dict[str, InterruptController] = {}
        self._run_lock = threading.Lock()

    def run(self, session: HarnessSession, *, replay_consent: bool = False) -> HarnessResult:
        return self._run_or_step(session, single_step=False, replay_consent=replay_consent)

    def _run_or_step(
        self,
        session: HarnessSession,
        *,
        single_step: bool,
        replay_consent: bool = False,
    ) -> HarnessResult:
        if not self._run_lock.acquire(blocking=False):
            return HarnessResult(
                ok=False,
                trace_id=session.trace_id,
                error="Another harness session is already running.",
            )
        try:
            return self._run_session(
                session,
                single_step=single_step,
                replay_consent=replay_consent,
            )
        finally:
            self._run_lock.release()

    def _run_session(
        self,
        session: HarnessSession,
        *,
        single_step: bool = False,
        replay_consent: bool = False,
    ) -> HarnessResult:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        adapter = self.adapters.get(session.agent)
        if adapter is None:
            return HarnessResult(
                ok=False,
                trace_id=session.trace_id,
                error=f"No harness adapter is registered for agent {session.agent!r}.",
            )

        tool_spec = getattr(adapter, "tool_spec", {"name": session.agent})
        approval_arguments = getattr(adapter, "approval_arguments", None)
        arguments = approval_arguments(session) if callable(approval_arguments) else {}
        decision = self.approval_policy.evaluate(
            tool_spec,
            arguments,
            session,
            registry=self.components.get("action_registry"),
        )
        delegated = bool(getattr(adapter, "confirmation_delegated", False))
        if not decision.allowed or (
            decision.requires_confirm and session.status != "approved" and not delegated
        ):
            error = decision.reason if not decision.allowed else "Explicit approval is required."
            session.status = "blocked"
            self.recovery.checkpoint(session, replay_consent=replay_consent)
            return HarnessResult(ok=False, trace_id=session.trace_id, error=error)

        safe_agent = (
            session.agent
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", session.agent)
            else "unclassified"
        )
        safe_session_id = (
            session.id
            if re.fullmatch(r"[A-Fa-f0-9-]{1,64}", session.id)
            else "session-" + hashlib.sha256(session.id.encode("utf-8")).hexdigest()
        )
        trace_id = self.tracer.start_run(agent=safe_agent, session_id=safe_session_id)
        session.trace_id = trace_id
        session.status = "running"
        self.tracer.event(
            "approval",
            tool=safe_agent,
            outcome="delegated" if delegated and decision.requires_confirm else "approved",
        )
        self.recovery.checkpoint(session, replay_consent=replay_consent)
        span_id = self.tracer.start_span(safe_agent, tool=safe_agent)
        interrupt = InterruptController()
        self._active_adapters[session.id] = adapter
        self._active_interrupts[session.id] = interrupt
        if hasattr(adapter, "interrupt_controller"):
            adapter.interrupt_controller = interrupt
        try:
            if decision.requires_confirm:
                session.status = "approved"
            result = (
                adapter.step(session)
                if single_step
                else adapter.run(session)
            )
            if not isinstance(result, HarnessResult):
                raise TypeError("Harness adapters must return HarnessResult.")
            result.trace_id = trace_id
            session.status = (
                "paused" if single_step and result.ok else
                "completed" if result.ok else
                "failed"
            )
            session.history.append({
                "type": "adapter_result",
                "agent": session.agent,
                "ok": result.ok,
                "step_count": len(result.steps),
            })
            self.tracer.end_span(span_id, ok=result.ok, tool=safe_agent)
            self.tracer.end_run(
                ok=result.ok,
                tokens=_token_total(result.usage),
                error_code="" if result.ok else "adapter_failed",
                status=session.status,
            )
            self.recovery.checkpoint(session, replay_consent=replay_consent)
            return result
        except Exception as exc:
            session.status = "failed"
            self.tracer.end_span(
                span_id,
                ok=False,
                tool=safe_agent,
                error_code=type(exc).__name__,
            )
            self.tracer.end_run(
                ok=False,
                error_code=type(exc).__name__,
                status=session.status,
            )
            self.recovery.checkpoint(session, replay_consent=replay_consent)
            return HarnessResult(
                ok=False,
                trace_id=trace_id,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._active_adapters.pop(session.id, None)
            self._active_interrupts.pop(session.id, None)
            if hasattr(adapter, "interrupt_controller"):
                adapter.interrupt_controller = None

    def step(self, session: HarnessSession, *, replay_consent: bool = False) -> HarnessResult:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        return self._run_or_step(
            session,
            single_step=True,
            replay_consent=replay_consent,
        )

    def stop(self, session_id: str) -> None:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        interrupt = self._active_interrupts.get(session_id)
        if interrupt is None:
            raise KeyError(f"No active harness run for session {session_id!r}.")
        interrupt.stop()

    def pause(self, session_id: str) -> None:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        interrupt = self._active_interrupts.get(session_id)
        if interrupt is None:
            raise KeyError(f"No active harness run for session {session_id!r}.")
        interrupt.pause()

    def continue_session(self, session_id: str) -> None:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        interrupt = self._active_interrupts.get(session_id)
        if interrupt is None:
            raise KeyError(f"No active harness run for session {session_id!r}.")
        interrupt.resume()

    def resume(self, session_id: str, *, replay_consent: bool = False) -> HarnessResult:
        if not self.enabled:
            raise RuntimeError("Harness is disabled; set JARVIS_HARNESS=1 to enable it.")
        session = self.recovery.restore(session_id, replay_consent=replay_consent)
        if not session.goal:
            return HarnessResult(
                ok=False,
                trace_id=session.trace_id,
                error=session.recovery_reason or (
                    "Checkpoint contains metadata only; resuming requires an "
                    "explicitly supplied goal and history."
                ),
            )
        return self.run(session, replay_consent=replay_consent)


def _token_total(usage: dict[str, Any]) -> int | None:
    total = usage.get("total_tokens")
    if isinstance(total, int) and not isinstance(total, bool):
        return total
    inputs, outputs = usage.get("input_tokens"), usage.get("output_tokens")
    if all(isinstance(value, int) and not isinstance(value, bool) for value in (inputs, outputs)):
        return inputs + outputs
    return None

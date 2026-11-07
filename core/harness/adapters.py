from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from core.harness.runtime import HarnessResult
from core.harness.session import HarnessSession


class ComputerLoopAdapter:
    """Translate the existing ComputerLoop result without changing its API."""

    tool_spec = {"name": "computer_use_loop", "risk_class": "write"}
    confirmation_delegated = False

    def __init__(self, loop: Any) -> None:
        self.loop = loop
        self.interrupt_controller = None

    @staticmethod
    def approval_arguments(session: HarnessSession) -> dict[str, Any]:
        workspace = next(
            (
                item.get("workspace")
                for item in session.artifacts
                if isinstance(item, dict) and isinstance(item.get("workspace"), str)
            ),
            None,
        )
        arguments: dict[str, Any] = {"goal": session.goal}
        if workspace is not None:
            arguments["workspace"] = workspace
        return arguments

    def run(self, session: HarnessSession, *, single_step: bool = False) -> HarnessResult:
        workspace = next(
            (
                item.get("workspace")
                for item in session.artifacts
                if isinstance(item, dict) and isinstance(item.get("workspace"), str)
            ),
            None,
        )
        previous_interrupt = getattr(self.loop, "interrupt_controller", None)
        if self.interrupt_controller is not None:
            self.loop.interrupt_controller = self.interrupt_controller
        try:
            if single_step:
                raw = self.loop.run(session.goal, workspace=workspace, max_steps=1)
            else:
                raw = self.loop.run(session.goal, workspace=workspace)
        finally:
            self.loop.interrupt_controller = previous_interrupt
        payload = raw.to_dict() if callable(getattr(raw, "to_dict", None)) else raw
        if not isinstance(payload, dict):
            raise TypeError("ComputerLoop must return a result object or dictionary.")
        ok = payload.get("status") in {"completed", "success", "paused"}
        return HarnessResult(
            ok=ok,
            steps=list(payload.get("steps", [])),
            trace_id=session.trace_id,
            artifacts=_artifact_metadata(payload),
            error=(
                None
                if ok
                else str(
                    payload.get("status")
                    if payload.get("status") == "stopped"
                    else payload.get("summary", payload.get("status", "failed"))
                )
            ),
        )

    def step(self, session: HarnessSession) -> HarnessResult:
        return self.run(session, single_step=True)

    def stop(self, session_id: str) -> None:
        del session_id
        if self.interrupt_controller is None:
            raise RuntimeError("ComputerLoop has no active harness interrupt controller.")
        self.interrupt_controller.stop()

    def pause(self) -> None:
        if self.interrupt_controller is None:
            raise RuntimeError("ComputerLoop has no active harness interrupt controller.")
        self.interrupt_controller.pause()

    def resume(self) -> None:
        if self.interrupt_controller is None:
            raise RuntimeError("ComputerLoop has no active harness interrupt controller.")
        self.interrupt_controller.resume()


class AgentLoopAdapter:
    """Adapt AgentLoop's async dictionary result to the harness result contract."""

    tool_spec = {"name": "agent_loop", "risk_class": "write"}
    confirmation_delegated = False

    def __init__(self, loop_factory: Callable[[HarnessSession], Any] | None = None) -> None:
        self.loop_factory = loop_factory
        self.interrupt_controller = None

    def run(self, session: HarnessSession, *, single_step: bool = False) -> HarnessResult:
        if session.status != "approved":
            raise PermissionError("AgentLoop requires an approved session.")
        loop = (
            self.loop_factory(session)
            if self.loop_factory is not None
            else _default_agent_loop(
                session,
                single_step=single_step,
                interrupt_controller=self.interrupt_controller,
            )
        )
        raw = _run_coroutine(loop.run(session.goal))
        if not isinstance(raw, dict):
            raise TypeError("AgentLoop must return a result dictionary.")
        status = raw.get("result")
        steps = raw.get("steps", 0)
        successful = status == "success" or (single_step and status == "max_steps")
        return HarnessResult(
            ok=successful,
            steps=[{"count": steps, **({"status": status} if single_step else {})}],
            trace_id=session.trace_id,
            error=None if successful else str(raw.get("reason", status or "failed")),
        )

    def step(self, session: HarnessSession) -> HarnessResult:
        return self.run(session, single_step=True)

    def stop(self, session_id: str) -> None:
        del session_id
        if self.interrupt_controller is None:
            raise RuntimeError("AgentLoop has no active harness interrupt controller.")
        self.interrupt_controller.stop()

    def pause(self) -> None:
        if self.interrupt_controller is None:
            raise RuntimeError("AgentLoop has no active harness interrupt controller.")
        self.interrupt_controller.pause()

    def resume(self) -> None:
        if self.interrupt_controller is None:
            raise RuntimeError("AgentLoop has no active harness interrupt controller.")
        self.interrupt_controller.resume()


def _default_agent_loop(
    session: HarnessSession,
    *,
    single_step: bool = False,
    interrupt_controller: Any = None,
) -> Any:
    from core.agent_loop import AgentLoop, resolve_max_steps

    requested = next(
        (
            item.get("max_steps")
            for item in session.artifacts
            if isinstance(item, dict) and "max_steps" in item
        ),
        None,
    )
    maximum = 1 if single_step else resolve_max_steps(requested)
    return AgentLoop(
        max_steps=maximum,
        confirm_session=lambda _prompt: session.status == "approved",
        interrupt_controller=interrupt_controller,
    )


def _run_coroutine(awaitable: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result: dict[str, Any] = {}
    error: dict[str, BaseException] = {}

    def run() -> None:
        try:
            result["value"] = asyncio.run(awaitable)
        except Exception as exc:
            error["exception"] = exc

    worker = threading.Thread(target=run, name="harness-agent-adapter")
    worker.start()
    worker.join()
    if "exception" in error:
        raise error["exception"]
    return result.get("value")


def _artifact_metadata(payload: dict[str, Any]) -> list[dict[str, Any]]:
    artifacts = payload.get("artifacts", [])
    if not isinstance(artifacts, list):
        return []
    allowed = {"id", "type", "name", "status", "sha256", "size"}
    return [
        {key: value for key, value in item.items() if key in allowed}
        for item in artifacts
        if isinstance(item, dict)
    ]

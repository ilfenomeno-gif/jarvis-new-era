"""Confirmation-gated execution through the unified ComputerLoop."""

from __future__ import annotations

import os

from core.computer_action_support import emit, request_confirmed_callback
from core.computer_use import (
    arm_emergency_stop,
    emergency_stop_triggered,
    require_allowed_foreground,
)


def run(
    parameters=None,
    *,
    goal=None,
    workspace=None,
    task=None,
    computer_agent=None,
    computer_loop=None,
    **_context,
):
    values = parameters or {}
    goal = goal if goal is not None else values.get("goal")
    workspace = workspace if workspace is not None else values.get("workspace")
    task = task if task is not None else values.get("task")

    if isinstance(goal, str) and goal.strip():
        if os.environ.get("JARVIS_COMPUTER_LOOP", "0") != "1":
            return {
                "ok": False,
                "error": "computer_loop_disabled",
                "reason": "Set JARVIS_COMPUTER_LOOP=1 to enable unified loop tasks.",
            }

        def execute_loop():
            from core.computer_loop import ComputerLoop

            emit("task_start", status="running", action=goal)
            owns_loop = computer_loop is None
            loop = computer_loop or ComputerLoop()
            try:
                result = loop.run(goal=goal, workspace=workspace)
            finally:
                if owns_loop:
                    loop.close()
            output = result.to_dict()
            status = "idle" if output["status"] == "completed" else "error"
            emit("task_done", status=status, action=goal, result=output)
            return str(output)

        return request_confirmed_callback(
            "computer_task",
            "Conferma task Computer Use",
            goal,
            execute_loop,
        )

    if not isinstance(task, str) or not task.strip():
        return {"ok": False, "error": "invalid_goal", "reason": "goal or task must be non-empty text."}
    if computer_agent is None:
        return {"ok": False, "error": "computer_agent_unavailable"}
    try:
        arm_emergency_stop()
        if emergency_stop_triggered():
            raise RuntimeError("Computer Use emergency stop is active.")
        require_allowed_foreground()
    except (OSError, PermissionError, RuntimeError) as exc:
        reason = f"Computer Use unavailable: {type(exc).__name__}: {exc}"
        emit("error", status="stopped", reason=reason)
        return {"ok": False, "error": "foreground_blocked", "reason": reason}

    def execute_agent():
        require_allowed_foreground()
        if emergency_stop_triggered():
            raise RuntimeError("Computer Use emergency stop is active.")
        emit("task_start", status="running", action=task)
        result = computer_agent.execute_task(task)
        emit("task_done", status="idle", action=task, result=result.summary)
        return result.summary

    return request_confirmed_callback(
        "computer_task",
        "Conferma task Computer Use",
        task,
        execute_agent,
    )


TOOL = {
    "name": "computer_task",
    "description": (
        "Run a planned, verified terminal/browser goal when JARVIS_COMPUTER_LOOP=1, "
        "or execute a supported legacy ComputerAgent task using task. Each operation "
        "requires an on-screen human confirmation."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "goal": {"type": "STRING"},
            "workspace": {"type": "STRING", "nullable": True},
            "task": {"type": "STRING"},
        },
    },
    "risk_class": "write",
    "handler": run,
}

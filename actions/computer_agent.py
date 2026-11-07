"""Expose the local ComputerAgent behind action-registry confirmation."""

from __future__ import annotations

from typing import Any

from agents.computer_agent import ComputerAgent


def computer_task(
    parameters: dict[str, Any] | None = None,
    *,
    computer_agent: ComputerAgent | None = None,
    **_context: Any,
) -> str:
    from actions.computer_task import run

    return run(parameters=parameters, computer_agent=computer_agent)

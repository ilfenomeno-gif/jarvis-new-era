from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass
class WorkerContext:
    task_id: str
    role: str
    cancelled: asyncio.Event
    _report: Callable[[float, str], Awaitable[None]]

    async def report_progress(self, percent: float, message: str = "") -> None:
        """Report normalized progress in the inclusive range 0.0–1.0."""
        await self._report(percent, message)


class Worker(Protocol):
    role: str
    tools: list[str]
    timeout_seconds: float

    async def run(self, prompt: str, ctx: WorkerContext) -> str: ...

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable
from typing import Protocol

from core.task_workers import WorkerContext

_MAX_EMBEDDED_BROWSERS = 2


class EmbeddedBrowserOpener(Protocol):
    async def __call__(
        self, task_id: str, url: str, ctx: WorkerContext
    ) -> str: ...


class ExternalBrowserOpener(Protocol):
    def __call__(self, url: str) -> Awaitable[None] | None: ...


class TaskBrowserPool:
    """Keep up to two embedded task browsers active; overflow opens externally."""

    def __init__(
        self,
        embedded_opener: EmbeddedBrowserOpener,
        external_opener: ExternalBrowserOpener,
    ):
        self._embedded_opener = embedded_opener
        self._external_opener = external_opener
        self._lock = asyncio.Lock()
        self._active: dict[str, str] = {}

    @property
    def active_task_ids(self) -> tuple[str, ...]:
        return tuple(self._active)

    async def open_and_read(
        self, task_id: str, url: str, ctx: WorkerContext
    ) -> str:
        if not task_id or not isinstance(task_id, str):
            raise ValueError("task_id must be non-empty text")
        if not isinstance(url, str) or not url:
            raise ValueError("url must be non-empty text")
        async with self._lock:
            if task_id in self._active:
                raise ValueError(f"Task {task_id} already owns an embedded browser")
            use_embedded = len(self._active) < _MAX_EMBEDDED_BROWSERS
            if use_embedded:
                self._active[task_id] = url

        if not use_embedded:
            result = self._external_opener(url)
            if inspect.isawaitable(result):
                await result
            return f"Embedded browser limit reached; opened externally: {url}"

        try:
            operation = asyncio.create_task(self._embedded_opener(task_id, url, ctx))
            cancellation = asyncio.create_task(ctx.cancelled.wait())
            try:
                done, _ = await asyncio.wait(
                    (operation, cancellation),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancellation in done:
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                    raise asyncio.CancelledError
                return await operation
            finally:
                if not operation.done():
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                cancellation.cancel()
                await asyncio.gather(cancellation, return_exceptions=True)
        finally:
            async with self._lock:
                self._active.pop(task_id, None)

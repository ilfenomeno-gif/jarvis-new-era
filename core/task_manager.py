from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Literal

from core.task_workers import WorkerContext

TaskStatus = Literal["pending", "running", "done", "failed", "cancelled"]
TaskEventType = Literal[
    "task.started",
    "task.progress",
    "task.done",
    "task.failed",
    "task.cancelled",
    "task.snapshot",
]
_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_STATE_VERSION = 1
_LOGGER = logging.getLogger("jarvis.tasks.manager")


@dataclass
class Task:
    task_id: str
    role: str
    prompt: str
    status: TaskStatus
    created_at: float
    updated_at: float
    started_at: float | None
    finished_at: float | None
    progress: float
    progress_message: str
    notify_when_done: bool
    timeout_seconds: float
    result: str | None
    error: str | None
    revision: int


@dataclass(frozen=True)
class TaskEvent:
    event_id: int
    type: TaskEventType
    task_id: str
    role: str
    status: str
    timestamp: float
    progress: float
    message: str


WorkerFactory = Callable[[Task, WorkerContext], Awaitable[str]]


class TaskManager:
    """Manage async worker task state, persistence, lifecycle and subscribers."""

    def __init__(self, state_path: Path, max_concurrent: int = 3):
        """Create an unstarted manager; state is loaded by the async ``start`` method."""
        if (
            isinstance(max_concurrent, bool)
            or not isinstance(max_concurrent, int)
            or max_concurrent < 1
        ):
            raise ValueError("max_concurrent must be a positive integer")
        self.state_path = Path(state_path)
        self.max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._tasks: dict[str, Task] = {}
        self._factories: dict[str, WorkerFactory] = {}
        self._active: dict[str, asyncio.Task[None]] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._running_since: dict[str, float] = {}
        self._pending: deque[str] = deque()
        self._subscribers: set[asyncio.Queue[TaskEvent | None]] = set()
        self._event_id = 0
        self._watchdog_changed = asyncio.Event()
        self._watchdog_task: asyncio.Task[None] | None = None
        self._closed = False
        self._started = False

    async def start(self) -> None:
        """Load persisted state once and start the running-task watchdog."""
        async with self._lock:
            if self._closed:
                raise RuntimeError("TaskManager is shut down")
            if self._started:
                return
            self._load()
            self._started = True
            self._ensure_watchdog_locked()

    async def create(
        self,
        role: str,
        prompt: str,
        *,
        notify_when_done: bool = True,
        timeout_seconds: float = 300,
    ) -> Task:
        """Create and persist a pending task without scheduling its worker."""
        if not isinstance(role, str) or not role.strip():
            raise ValueError("role must be a non-empty string")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if not isinstance(notify_when_done, bool):
            raise TypeError("notify_when_done must be a bool")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")

        async with self._lock:
            self._ensure_open()
            if not self._started:
                raise RuntimeError("TaskManager.start() must be called before create()")
            now = time.time()
            task = Task(
                task_id=uuid.uuid4().hex,
                role=role.strip(),
                prompt=prompt,
                status="pending",
                created_at=now,
                updated_at=now,
                started_at=None,
                finished_at=None,
                progress=0.0,
                progress_message="",
                notify_when_done=notify_when_done,
                timeout_seconds=float(timeout_seconds),
                result=None,
                error=None,
                revision=0,
            )
            self._tasks[task.task_id] = task
            self._persist()
            return replace(task)

    async def start_task(
        self,
        task_id: str,
        factory: WorkerFactory,
    ) -> None:
        """Queue a task's worker factory, starting it when a concurrency slot is free."""
        await self._start_worker(task_id, factory)

    async def _start_worker(self, task_id: str, factory: WorkerFactory) -> None:
        async with self._lock:
            self._ensure_open()
            if not self._started:
                raise RuntimeError("TaskManager.start() must be called before start_task()")
            task = self._require_task(task_id)
            if task.status != "pending" or task_id in self._factories:
                raise ValueError(f"Task {task_id} is not available to start")
            if not callable(factory):
                raise TypeError("factory must be callable")
            self._factories[task_id] = factory
            self._pending.append(task_id)
            self._pump_locked()

    async def complete(self, task_id: str, result: str) -> None:
        """Mark a task done; terminal tasks are left unchanged."""
        if not isinstance(result, str):
            raise TypeError("result must be a string")
        await self._finish(task_id, "done", result=result)

    async def fail(self, task_id: str, error: str) -> None:
        """Mark a task failed; terminal tasks are left unchanged."""
        if not isinstance(error, str) or not error:
            raise ValueError("error must be a non-empty string")
        await self._finish(task_id, "failed", error=error)

    async def cancel(self, task_id: str) -> None:
        """Request cooperative cancellation and wait at most five seconds for the worker."""
        async with self._lock:
            task = self._require_task(task_id)
            if task.status in _TERMINAL_STATUSES:
                return
            cancellation = self._cancel_events.get(task_id)
            if task.status == "running" and cancellation is not None:
                if not cancellation.is_set():
                    cancellation.set()
                    task.updated_at = time.time()
                    task.revision += 1
                    self._persist()
                worker_task = self._active.get(task_id)
            else:
                worker_task = None
                self._finish_locked(task, "cancelled")
                self._pump_locked()
                self._persist()
                return

        if worker_task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(worker_task), timeout=5.0)
        except TimeoutError:
            await self.fail(task_id, "cancel_timeout")
        except asyncio.CancelledError:
            raise

    async def get(self, task_id: str) -> Task | None:
        """Return a detached task snapshot, or ``None`` for an unknown id."""
        async with self._lock:
            task = self._tasks.get(task_id)
            return replace(task) if task is not None else None

    async def list(self, status: str | None = None) -> list[Task]:
        """Return detached task snapshots, optionally filtered by status."""
        async with self._lock:
            return [
                replace(task)
                for task in self._tasks.values()
                if status is None or task.status == status
            ]

    def subscribe(self) -> AsyncIterator[TaskEvent]:
        """Subscribe to ordered events, including a snapshot of existing tasks."""
        async def events() -> AsyncIterator[TaskEvent]:
            queue: asyncio.Queue[TaskEvent | None] = asyncio.Queue()
            async with self._lock:
                self._subscribers.add(queue)
                for task in self._tasks.values():
                    self._publish_locked(task, "task.snapshot", task.progress_message)
                if self._closed:
                    queue.put_nowait(None)
                self._persist()
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        return
                    yield event
            finally:
                async with self._lock:
                    self._subscribers.discard(queue)

        return events()

    async def shutdown(self) -> None:
        """Cancel active workers, persist state and stop the watchdog."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            for task in self._tasks.values():
                if task.status == "running":
                    cancellation = self._cancel_events.get(task.task_id)
                    if cancellation is not None:
                        cancellation.set()
                    self._finish_locked(task, "cancelled")
            self._pending.clear()
            self._persist()
            active = list(self._active.values())
            for worker_task in active:
                worker_task.cancel()
            watchdog = self._watchdog_task
            if watchdog is not None:
                watchdog.cancel()
            self._watchdog_changed.set()

        if active:
            await asyncio.gather(*active, return_exceptions=True)
        if watchdog is not None:
            await asyncio.gather(watchdog, return_exceptions=True)

        async with self._lock:
            for queue in self._subscribers:
                queue.put_nowait(None)
            self._subscribers.clear()

    async def snapshot(self) -> list[Task]:
        """Return detached snapshots of all managed tasks."""
        return await self.list()

    async def _finish(
        self,
        task_id: str,
        status: Literal["done", "failed", "cancelled"],
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            task = self._require_task(task_id)
            if task.status in _TERMINAL_STATUSES:
                return
            self._finish_locked(task, status, result=result, error=error)
            self._pump_locked()
            self._persist()

    def _finish_locked(
        self,
        task: Task,
        status: Literal["done", "failed", "cancelled"],
        *,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        if task.status in _TERMINAL_STATUSES:
            return
        task.status = status
        task.result = result
        task.error = error
        task.finished_at = time.time()
        if status == "done":
            task.progress = 1.0
        task.updated_at = task.finished_at
        task.revision += 1
        event_type: TaskEventType = f"task.{status}"
        self._publish_locked(task, event_type, error or task.progress_message)

        if status in {"cancelled", "failed"}:
            cancellation = self._cancel_events.get(task.task_id)
            if cancellation is not None:
                cancellation.set()
        current = asyncio.current_task()
        worker_task = self._active.get(task.task_id)
        if worker_task is not None and worker_task is not current:
            cancellation = self._cancel_events.get(task.task_id)
            if cancellation is not None:
                cancellation.set()
            worker_task.cancel()
        if task.task_id in self._pending:
            self._pending = deque(
                pending_id for pending_id in self._pending if pending_id != task.task_id
            )
            self._factories.pop(task.task_id, None)
        self._watchdog_changed.set()

    async def _run_worker(
        self,
        task_id: str,
        factory: WorkerFactory,
        context: WorkerContext,
    ) -> None:
        task = self._tasks[task_id]
        try:
            try:
                result = await factory(replace(task), context)
            except asyncio.CancelledError:
                current = asyncio.current_task()
                async with self._lock:
                    task = self._tasks.get(task_id)
                    if task is not None and task.status not in _TERMINAL_STATUSES:
                        if context.cancelled.is_set():
                            self._finish_locked(task, "cancelled")
                        else:
                            self._finish_locked(
                                task, "failed", error="worker_cancelled"
                            )
                        self._persist()
                if current is not None and current.cancelling():
                    raise
                return
            except Exception as exc:
                _LOGGER.exception(
                    "Worker failed for task %s (role=%s)",
                    task_id,
                    task.role,
                )
                await self.fail(
                    task_id,
                    f"worker_error: {type(exc).__name__}: {exc}",
                )
                return

            if not isinstance(result, str):
                await self.fail(
                    task_id,
                    "worker_contract_violation: expected str, "
                    f"got {type(result).__name__}",
                )
                return
            if context.cancelled.is_set():
                await self._finish(task_id, "cancelled")
                return
            try:
                await self.complete(task_id, result)
            except Exception as exc:
                _LOGGER.exception("complete() failed for task %s", task_id)
                await self.fail(task_id, f"complete_failed: {exc}")
        finally:
            async with self._lock:
                current = asyncio.current_task()
                if self._active.get(task_id) is current:
                    self._active.pop(task_id, None)
                    self._running_since.pop(task_id, None)
                    self._cancel_events.pop(task_id, None)
                    self._factories.pop(task_id, None)
                    self._watchdog_changed.set()
                    if not self._closed:
                        self._pump_locked()

    async def _report_progress(self, task_id: str, progress: float, message: str) -> None:
        if isinstance(progress, bool) or not isinstance(progress, (int, float)):
            raise TypeError("progress must be a number in the range 0.0–1.0")
        if not math.isfinite(progress):
            raise ValueError("progress must be finite")
        if not isinstance(message, str):
            raise TypeError("message must be a string")

        async with self._lock:
            task = self._require_task(task_id)
            if task.status != "running":
                return
            cancellation = self._cancel_events.get(task_id)
            if cancellation is not None and cancellation.is_set():
                return
            task.progress = max(task.progress, min(1.0, max(0.0, float(progress))))
            task.progress_message = message
            task.updated_at = time.time()
            task.revision += 1
            self._publish_locked(task, "task.progress", message)
            self._persist()

    def _pump_locked(self) -> None:
        if self._closed:
            return
        while self._pending and len(self._active) < self.max_concurrent:
            task_id = self._pending.popleft()
            task = self._tasks[task_id]
            if task.status != "pending":
                continue
            factory = self._factories[task_id]
            now = time.time()
            task.status = "running"
            task.started_at = now
            task.updated_at = now
            task.revision += 1
            cancellation = asyncio.Event()
            self._cancel_events[task_id] = cancellation
            context = WorkerContext(
                task_id=task_id,
                role=task.role,
                cancelled=cancellation,
                _report=lambda progress, message, task_id=task_id: (
                    self._report_progress(task_id, progress, message)
                ),
            )
            self._publish_locked(task, "task.started", "")
            self._running_since[task_id] = asyncio.get_running_loop().time()
            worker_task = asyncio.create_task(
                self._run_worker(task_id, factory, context),
                name=f"jarvis-task-{task_id}",
            )
            self._active[task_id] = worker_task
            self._watchdog_changed.set()
            self._persist()

    def _ensure_watchdog_locked(self) -> None:
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(
                self._watchdog_loop(), name="jarvis-task-watchdog"
            )

    async def _watchdog_loop(self) -> None:
        try:
            while True:
                async with self._lock:
                    if self._closed:
                        return
                    deadlines = [
                        self._running_since[task_id] + self._tasks[task_id].timeout_seconds
                        for task_id in self._running_since
                        if self._tasks[task_id].status == "running"
                    ]
                    self._watchdog_changed.clear()
                    delay = (
                        max(0.0, min(deadlines) - asyncio.get_running_loop().time())
                        if deadlines
                        else None
                    )
                try:
                    if delay is None:
                        await self._watchdog_changed.wait()
                    else:
                        await asyncio.wait_for(self._watchdog_changed.wait(), timeout=delay)
                except TimeoutError:
                    now = asyncio.get_running_loop().time()
                    async with self._lock:
                        expired = [
                            task_id
                            for task_id, started in self._running_since.items()
                            if self._tasks[task_id].status == "running"
                            and now - started >= self._tasks[task_id].timeout_seconds
                        ]
                    for task_id in expired:
                        await self.fail(task_id, "timeout")
        except asyncio.CancelledError:
            return

    def _publish_locked(
        self,
        task: Task,
        event_type: TaskEventType,
        message: str,
    ) -> None:
        self._event_id += 1
        event = TaskEvent(
            event_id=self._event_id,
            type=event_type,
            task_id=task.task_id,
            role=task.role,
            status=task.status,
            timestamp=time.time(),
            progress=task.progress,
            message=message,
        )
        for queue in self._subscribers:
            queue.put_nowait(event)

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != _STATE_VERSION:
            raise ValueError(f"Unsupported task state file: {self.state_path}")
        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list):
            raise ValueError(f"Invalid task state file: {self.state_path}")
        event_id = data.get("event_id", 0)
        if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id < 0:
            raise ValueError(f"Invalid event_id in task state file: {self.state_path}")
        self._event_id = event_id
        now = time.time()
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                raise ValueError(f"Invalid task record in {self.state_path}")
            task = Task(**raw)
            self._validate_loaded_task(task)
            if task.status == "running":
                task.status = "failed"
                task.error = "interrupted_by_restart"
                task.finished_at = now
                task.updated_at = now
                task.revision += 1
            if task.task_id in self._tasks:
                raise ValueError(f"Duplicate task id in {self.state_path}: {task.task_id}")
            self._tasks[task.task_id] = task
        if any(task.error == "interrupted_by_restart" for task in self._tasks.values()):
            self._persist()

    @staticmethod
    def _validate_loaded_task(task: Task) -> None:
        if task.status not in {"pending", "running", *_TERMINAL_STATUSES}:
            raise ValueError(f"Invalid task status in persisted task {task.task_id}")
        if not task.task_id or not task.role or not isinstance(task.prompt, str):
            raise ValueError(f"Invalid persisted task {task.task_id}")
        if (
            not isinstance(task.progress, (int, float))
            or isinstance(task.progress, bool)
            or not math.isfinite(task.progress)
            or not 0.0 <= task.progress <= 1.0
        ):
            raise ValueError(f"Invalid progress in persisted task {task.task_id}")

    def _persist(self) -> None:
        """Atomically persist state; retry Windows antivirus PermissionErrors.

        Windows may return PermissionError if antivirus scans the temp file;
        retry with exponential backoff.
        """
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _STATE_VERSION,
            "event_id": self._event_id,
            "tasks": [asdict(task) for task in self._tasks.values()],
        }
        temporary_path = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for delay in (0.05, 0.1, 0.15):
            try:
                os.replace(temporary_path, self.state_path)
                return
            except PermissionError:
                time.sleep(delay)
        os.replace(temporary_path, self.state_path)

    def _require_task(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError:
            raise KeyError(f"Unknown task: {task_id}") from None

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("TaskManager is shut down")

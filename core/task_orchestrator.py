from __future__ import annotations

import asyncio
import inspect
import logging
import math
from collections.abc import Awaitable, Callable, Mapping

from core.task_manager import Task, TaskEvent, TaskManager
from core.task_workers import Worker

_LOGGER = logging.getLogger("jarvis.tasks.orchestrator")
_TASK_STATUSES = frozenset({"pending", "running", "done", "failed", "cancelled"})
TASK_TOOL_DECLARATIONS = [
    {
        "name": "delegate_task",
        "description": (
            "Start a silent background worker for a separate task. Only delegate "
            "work that can proceed independently while JARVIS handles the user."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "role": {"type": "STRING", "description": "Registered worker role."},
                "prompt": {"type": "STRING", "description": "The worker's bounded task."},
                "notify_when_done": {
                    "type": "BOOLEAN",
                    "description": "Queue a completion notice for when JARVIS is idle.",
                },
            },
            "required": ["role", "prompt"],
        },
    },
    {
        "name": "list_tasks",
        "description": "List background tasks, optionally filtered by lifecycle status.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "status": {
                    "type": "STRING",
                    "enum": ["pending", "running", "done", "failed", "cancelled"],
                }
            },
        },
    },
    {
        "name": "cancel_task",
        "description": "Cooperatively cancel a background task by its task id.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "STRING", "description": "Background task id."}
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_task_result",
        "description": "Read the current status and result of a background task.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task_id": {"type": "STRING", "description": "Background task id."}
            },
            "required": ["task_id"],
        },
    },
]

TaskNotification = Callable[[list[Task]], Awaitable[None] | None]


class TaskOrchestrator:
    """Expose task meta-tools and queue grouped completion notifications."""

    def __init__(
        self,
        manager: TaskManager,
        workers: Mapping[str, Worker] | None = None,
        *,
        idle_event: asyncio.Event | None = None,
        on_notification: TaskNotification | None = None,
        notification_window: float = 2.0,
    ):
        if (
            isinstance(notification_window, bool)
            or not isinstance(notification_window, (int, float))
            or not math.isfinite(notification_window)
            or notification_window < 0
        ):
            raise ValueError("notification_window must be a non-negative number")
        self.manager = manager
        self.idle_event = idle_event if idle_event is not None else asyncio.Event()
        if idle_event is None:
            self.idle_event.set()
        self.on_notification = on_notification
        self.notification_window = float(notification_window)
        self._workers: dict[str, Worker] = {}
        self._notification_queue: asyncio.Queue[Task] = asyncio.Queue()
        self._notification_groups: asyncio.Queue[list[Task]] = asyncio.Queue()
        self._listener: asyncio.Task[None] | None = None
        self._listener_ready = asyncio.Event()
        self._notifier: asyncio.Task[None] | None = None
        self._closed = False
        for key, worker in (workers or {}).items():
            if key != worker.role:
                raise ValueError("Worker mapping keys must match each worker's role")
            self.register_worker(worker)

    def register_worker(self, worker: Worker) -> None:
        """Register or replace a role for future delegated tasks."""
        if (
            not isinstance(worker.role, str)
            or not worker.role.strip()
            or worker.role != worker.role.strip()
        ):
            raise ValueError("worker role must be non-empty text")
        if (
            isinstance(worker.timeout_seconds, bool)
            or not isinstance(worker.timeout_seconds, (int, float))
            or not math.isfinite(worker.timeout_seconds)
            or worker.timeout_seconds <= 0
        ):
            raise ValueError("worker timeout_seconds must be positive")
        if not isinstance(worker.tools, list) or not all(
            isinstance(tool, str) and tool for tool in worker.tools
        ):
            raise ValueError("worker tools must be a list of non-empty strings")
        self._workers[worker.role] = worker

    def roles(self) -> tuple[str, ...]:
        """Return the roles currently available for delegation."""
        return tuple(sorted(self._workers))

    async def start(self) -> None:
        """Start the manager and background event/notification consumers."""
        if self._closed:
            raise RuntimeError("TaskOrchestrator is shut down")
        await self.manager.start()
        if self._listener is None or self._listener.done():
            self._listener_ready.clear()
            self._listener = asyncio.create_task(
                self._watch_task_events(), name="jarvis-task-event-listener"
            )
            await self._listener_ready.wait()
        if self._notifier is None or self._notifier.done():
            self._notifier = asyncio.create_task(
                self._deliver_notifications(), name="jarvis-task-notifier"
            )

    async def delegate_task(
        self,
        role: str,
        prompt: str,
        *,
        notify_when_done: bool = True,
    ) -> str:
        if self._closed:
            raise RuntimeError("TaskOrchestrator is shut down")
        worker = self._workers.get(role)
        if worker is None:
            raise ValueError(
                f"Unknown worker role {role!r}; available roles: {', '.join(self.roles())}"
            )
        task = await self.manager.create(
            role,
            prompt,
            notify_when_done=notify_when_done,
            timeout_seconds=worker.timeout_seconds,
        )
        await self.manager.start_task(
            task.task_id,
            lambda queued_task, ctx: worker.run(queued_task.prompt, ctx),
        )
        return task.task_id

    async def list_tasks(self, status: str | None = None) -> list[dict]:
        if status is not None and status not in _TASK_STATUSES:
            raise ValueError(f"Unknown task status: {status}")
        return [self._task_summary(task) for task in await self.manager.list(status)]

    async def cancel_task(self, task_id: str) -> dict | None:
        await self.manager.cancel(task_id)
        task = await self.manager.get(task_id)
        return self._task_summary(task) if task is not None else None

    async def get_task_result(self, task_id: str) -> dict | None:
        task = await self.manager.get(task_id)
        if task is None:
            return None
        return {
            "task_id": task.task_id,
            "role": task.role,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "progress": task.progress,
            "progress_message": task.progress_message,
        }

    async def handle_tool(self, name: str, arguments: dict) -> dict:
        """Dispatch a Gemini meta-tool call to the corresponding manager API."""
        if not isinstance(arguments, dict):
            raise TypeError("task tool arguments must be an object")
        if name == "delegate_task":
            task_id = await self.delegate_task(
                arguments.get("role"),
                arguments.get("prompt"),
                notify_when_done=arguments.get("notify_when_done", True),
            )
            task = await self.manager.get(task_id)
            return {
                "task_id": task_id,
                "status": task.status if task is not None else "unknown",
            }
        if name == "list_tasks":
            return {"tasks": await self.list_tasks(arguments.get("status"))}
        if name == "cancel_task":
            return {"task": await self.cancel_task(arguments.get("task_id"))}
        if name == "get_task_result":
            return {"task": await self.get_task_result(arguments.get("task_id"))}
        raise ValueError(f"Unknown task meta-tool: {name}")

    async def next_notification_group(self) -> list[Task]:
        """Return the next grouped completion notification when no callback is set."""
        return await self._notification_groups.get()

    async def shutdown(self) -> None:
        """Stop background consumers and shut down the task manager."""
        if self._closed:
            return
        self._closed = True
        background = [
            task for task in (self._listener, self._notifier) if task is not None
        ]
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        await self.manager.shutdown()

    async def _watch_task_events(self) -> None:
        events = self.manager.subscribe()
        next_event: asyncio.Task[TaskEvent] | None = None
        try:
            next_event = asyncio.create_task(anext(events))
            await asyncio.sleep(0)
            self._listener_ready.set()
            event = await next_event
            while True:
                if event.type != "task.done":
                    event = await anext(events)
                    continue
                task = await self.manager.get(event.task_id)
                if task is not None and task.notify_when_done:
                    self._notification_queue.put_nowait(task)
                event = await anext(events)
        except StopAsyncIteration:
            return
        except asyncio.CancelledError:
            raise
        finally:
            self._listener_ready.set()
            if next_event is not None and not next_event.done():
                next_event.cancel()
                await asyncio.gather(next_event, return_exceptions=True)
            await events.aclose()

    async def _deliver_notifications(self) -> None:
        while True:
            first = await self._notification_queue.get()
            grouped = {first.task_id: first}
            deadline = asyncio.get_running_loop().time() + self.notification_window
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    task = await asyncio.wait_for(
                        self._notification_queue.get(), timeout=remaining
                    )
                except TimeoutError:
                    break
                grouped[task.task_id] = task

            await self.idle_event.wait()
            if self._closed:
                return
            notifications = list(grouped.values())
            if self.on_notification is None:
                await self._notification_groups.put(notifications)
                continue
            try:
                result = self.on_notification(notifications)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                _LOGGER.exception("Task completion notification callback failed")

    @staticmethod
    def _task_summary(task: Task) -> dict:
        return {
            "task_id": task.task_id,
            "role": task.role,
            "status": task.status,
            "progress": task.progress,
            "progress_message": task.progress_message,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

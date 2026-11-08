from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from core.task_manager import TaskManager
from core.task_orchestrator import TASK_TOOL_DECLARATIONS, TaskOrchestrator


class _Worker:
    role = "writer"
    tools = ["write_file"]
    timeout_seconds = 2.0

    def __init__(self):
        self.started: list[str] = []

    async def run(self, prompt, ctx):
        self.started.append(prompt)
        await ctx.report_progress(0.5, "Working")
        return f"done: {prompt}"


@pytest_asyncio.fixture
async def orchestrator(tmp_path):
    manager = TaskManager(tmp_path / "tasks.json", max_concurrent=3)
    worker = _Worker()
    instance = TaskOrchestrator(manager, {"writer": worker})
    await instance.start()
    yield instance, worker
    await instance.shutdown()


@pytest.mark.asyncio
async def test_delegate_task_runs_registered_worker(orchestrator):
    instance, worker = orchestrator

    task_id = await instance.delegate_task("writer", "Write a poem")
    result = await _wait_for_status(instance, task_id, "done")

    assert worker.started == ["Write a poem"]
    assert result["result"] == "done: Write a poem"


@pytest.mark.asyncio
async def test_delegate_task_rejects_unknown_role(orchestrator):
    instance, _ = orchestrator

    with pytest.raises(ValueError, match="Unknown worker role"):
        await instance.delegate_task("missing", "Do work")

    assert await instance.list_tasks() == []


@pytest.mark.asyncio
async def test_task_meta_tools_dispatch(orchestrator):
    instance, _ = orchestrator

    delegated = await instance.handle_tool(
        "delegate_task",
        {"role": "writer", "prompt": "Draft"},
    )
    task_id = delegated["task_id"]
    await _wait_for_status(instance, task_id, "done")

    listed = await instance.handle_tool("list_tasks", {"status": "done"})
    fetched = await instance.handle_tool("get_task_result", {"task_id": task_id})

    assert listed["tasks"][0]["task_id"] == task_id
    assert fetched["task"]["result"] == "done: Draft"
    assert (await instance.handle_tool("get_task_result", {"task_id": "missing"}))[
        "task"
    ] is None


@pytest.mark.asyncio
async def test_cancel_task_meta_tool(orchestrator):
    instance, _ = orchestrator
    started = asyncio.Event()

    class WaitingWorker(_Worker):
        async def run(self, prompt, ctx):
            started.set()
            await ctx.cancelled.wait()
            return "cancelled cooperatively"

    instance.register_worker(WaitingWorker())
    task_id = await instance.delegate_task("writer", "Wait")
    await asyncio.wait_for(started.wait(), timeout=1)

    response = await instance.handle_tool("cancel_task", {"task_id": task_id})

    assert response["task"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_notifications_wait_for_idle_and_group_completions(tmp_path):
    manager = TaskManager(tmp_path / "tasks.json", max_concurrent=3)
    idle_event = asyncio.Event()
    notified = asyncio.Event()
    groups = []

    def on_notification(tasks):
        groups.append(tasks)
        notified.set()

    instance = TaskOrchestrator(
        manager,
        {"writer": _Worker()},
        idle_event=idle_event,
        on_notification=on_notification,
        notification_window=0.02,
    )
    await instance.start()

    first = await instance.delegate_task("writer", "First")
    second = await instance.delegate_task("writer", "Second")
    await _wait_for_status(instance, first, "done")
    await _wait_for_status(instance, second, "done")

    await asyncio.sleep(0.04)
    assert groups == []
    idle_event.set()
    await asyncio.wait_for(notified.wait(), timeout=1)

    assert len(groups) == 1
    assert {task.task_id for task in groups[0]} == {first, second}
    await instance.shutdown()


@pytest.mark.asyncio
async def test_invalid_task_status_is_rejected(orchestrator):
    instance, _ = orchestrator

    with pytest.raises(ValueError, match="Unknown task status"):
        await instance.list_tasks("unknown")


def test_task_tool_declarations_cover_meta_api():
    assert {declaration["name"] for declaration in TASK_TOOL_DECLARATIONS} == {
        "delegate_task",
        "list_tasks",
        "cancel_task",
        "get_task_result",
    }


async def _wait_for_status(instance, task_id: str, expected: str) -> dict:
    async def wait():
        while True:
            result = await instance.get_task_result(task_id)
            if result is not None and result["status"] == expected:
                return result
            await asyncio.sleep(0)

    return await asyncio.wait_for(wait(), timeout=1)

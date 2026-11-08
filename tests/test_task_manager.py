from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from core import task_manager as task_manager_module
from core.task_manager import TaskManager


@pytest_asyncio.fixture
async def manager(tmp_path):
    instance = TaskManager(tmp_path / "tasks.json")
    await instance.start()
    yield instance
    await instance.shutdown()


async def _next_type(events, event_type):
    while True:
        event = await asyncio.wait_for(anext(events), timeout=1)
        if event.type == event_type:
            return event


@pytest.mark.asyncio
async def test_create_returns_pending_task(manager):
    task = await manager.create("writer", "Write a poem")

    assert task.task_id
    assert task.status == "pending"
    assert task.progress == 0.0
    assert task.revision == 0


@pytest.mark.asyncio
async def test_start_transitions_to_running(manager):
    started = asyncio.Event()
    release = asyncio.Event()

    async def worker(task, _ctx):
        started.set()
        await release.wait()
        return task.prompt

    task = await manager.create("writer", "Write a poem")
    await manager.start_task(task.task_id, worker)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert (await manager.get(task.task_id)).status == "running"
    release.set()


@pytest.mark.asyncio
async def test_complete_sets_terminal_state(manager):
    task = await manager.create("writer", "Write a poem")

    await manager.complete(task.task_id, "Finished")
    result = await manager.get(task.task_id)

    assert result.status == "done"
    assert result.result == "Finished"
    assert result.finished_at is not None
    assert result.progress == 1.0


@pytest.mark.asyncio
async def test_fail_sets_terminal_state(manager):
    task = await manager.create("writer", "Write a poem")

    await manager.fail(task.task_id, "provider unavailable")
    result = await manager.get(task.task_id)

    assert result.status == "failed"
    assert result.error == "provider unavailable"


@pytest.mark.asyncio
async def test_cancel_before_start(manager):
    task = await manager.create("writer", "Write a poem")

    await manager.cancel(task.task_id)

    assert (await manager.get(task.task_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_during_run(manager):
    started = asyncio.Event()
    cancellation_seen = asyncio.Event()

    async def worker(_task, ctx):
        started.set()
        await ctx.cancelled.wait()
        cancellation_seen.set()
        return "stopped cooperatively"

    task = await manager.create("writer", "Write a poem")
    await manager.start_task(task.task_id, worker)
    await asyncio.wait_for(started.wait(), timeout=1)
    original_revision = (await manager.get(task.task_id)).revision
    await manager.cancel(task.task_id)
    assert (await manager.get(task.task_id)).revision == original_revision + 2
    await asyncio.wait_for(cancellation_seen.wait(), timeout=1)

    assert (await manager.get(task.task_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_worker_exception_fails_task_immediately(manager):
    task = await manager.create("writer", "Write a poem")
    events = manager.subscribe()
    assert (await anext(events)).type == "task.snapshot"

    async def worker(_task, _ctx):
        raise RuntimeError("provider failed")

    await manager.start_task(task.task_id, worker)
    terminal = await asyncio.wait_for(
        _next_type(events, "task.failed"),
        timeout=0.1,
    )
    result = await manager.get(task.task_id)

    assert terminal.task_id == task.task_id
    assert result.status == "failed"
    assert "RuntimeError" in result.error
    await events.aclose()


@pytest.mark.asyncio
async def test_worker_returns_none_fails_task(manager):
    task = await manager.create("writer", "Write a poem")
    events = manager.subscribe()
    assert (await anext(events)).type == "task.snapshot"

    await manager.start_task(task.task_id, lambda _task, _ctx: _return_none())
    terminal = await _next_type(events, "task.failed")
    result = await manager.get(task.task_id)

    assert terminal.task_id == task.task_id
    assert result.status == "failed"
    assert "contract_violation" in result.error
    await events.aclose()


async def _return_none():
    return None


@pytest.mark.asyncio
async def test_worker_cancel_still_works(manager):
    started = asyncio.Event()
    task = await manager.create("writer", "Write a poem")

    async def worker(_task, ctx):
        started.set()
        await ctx.cancelled.wait()
        return "stopped"

    await manager.start_task(task.task_id, worker)
    await asyncio.wait_for(started.wait(), timeout=1)
    await manager.cancel(task.task_id)

    assert (await manager.get(task.task_id)).status == "cancelled"


@pytest.mark.asyncio
async def test_persist_tolerates_permission_error(manager, monkeypatch):
    original_replace = task_manager_module.os.replace
    attempts = 0
    delays = []

    def flaky_replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise PermissionError("temporary antivirus lock")
        original_replace(source, destination)

    monkeypatch.setattr(task_manager_module.os, "replace", flaky_replace)
    monkeypatch.setattr(task_manager_module.time, "sleep", delays.append)

    task = await manager.create("writer", "Write a poem")

    assert attempts == 3
    assert delays == [0.05, 0.1]
    assert (await manager.get(task.task_id)).status == "pending"


@pytest.mark.asyncio
async def test_timeout_watchdog_fails_stuck_task(manager):
    started = asyncio.Event()
    events = manager.subscribe()
    snapshot = asyncio.create_task(anext(events))
    task = await manager.create("writer", "Write a poem", timeout_seconds=0.1)
    await manager.start_task(
        task.task_id,
        lambda _task, _ctx: _wait_forever(started),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    snapshot_event = await asyncio.wait_for(snapshot, timeout=1)
    assert snapshot_event.type == "task.snapshot"

    terminal = await _next_type(events, "task.failed")

    assert terminal.task_id == task.task_id
    assert (await manager.get(task.task_id)).error == "timeout"
    await events.aclose()


async def _wait_forever(started):
    started.set()
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_complete_is_idempotent(manager):
    task = await manager.create("writer", "Write a poem")
    await manager.complete(task.task_id, "first")
    first = await manager.get(task.task_id)

    await manager.complete(task.task_id, "second")
    second = await manager.get(task.task_id)

    assert second == first
    assert second.result == "first"


@pytest.mark.asyncio
async def test_persistence_roundtrip(tmp_path):
    state_path = tmp_path / "tasks.json"
    first_manager = TaskManager(state_path)
    await first_manager.start()
    original = await first_manager.create(
        "writer", "Write a poem", notify_when_done=False, timeout_seconds=45
    )
    await first_manager.shutdown()
    second_manager = TaskManager(state_path)
    await second_manager.start()

    assert await second_manager.get(original.task_id) == original

    await second_manager.shutdown()


@pytest.mark.asyncio
async def test_running_task_becomes_failed_on_restart(tmp_path):
    state_path = tmp_path / "tasks.json"
    first_manager = TaskManager(state_path)
    await first_manager.start()
    started = asyncio.Event()
    task = await first_manager.create("writer", "Write a poem")

    async def worker(_task, _ctx):
        started.set()
        await asyncio.Event().wait()
        return ""

    await first_manager.start_task(task.task_id, worker)
    await asyncio.wait_for(started.wait(), timeout=1)
    restarted_manager = TaskManager(state_path)
    await restarted_manager.start()
    recovered = await restarted_manager.get(task.task_id)

    assert recovered.status == "failed"
    assert recovered.error == "interrupted_by_restart"

    await first_manager.shutdown()
    await restarted_manager.shutdown()


@pytest.mark.asyncio
async def test_subscribe_receives_events_in_order(manager):
    task = await manager.create("writer", "Write a poem")
    events = manager.subscribe()
    snapshot = await anext(events)

    async def worker(_task, ctx):
        await ctx.report_progress(0.5, "Draft")
        return "Done"

    await manager.start_task(task.task_id, worker)
    observed = [snapshot]
    for event_type in ("task.started", "task.progress", "task.done"):
        observed.append(await _next_type(events, event_type))

    assert [event.type for event in observed] == [
        "task.snapshot",
        "task.started",
        "task.progress",
        "task.done",
    ]
    assert [event.event_id for event in observed] == sorted(
        event.event_id for event in observed
    )
    await events.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_type", ("done", "failed", "cancelled"))
async def test_two_subscribers_both_get_terminal_events(manager, terminal_type):
    task = await manager.create("writer", "Write a poem")
    first = manager.subscribe()
    second = manager.subscribe()
    assert (await anext(first)).type == "task.snapshot"
    assert (await anext(second)).type == "task.snapshot"

    if terminal_type == "done":
        await manager.complete(task.task_id, "Done")
    elif terminal_type == "failed":
        await manager.fail(task.task_id, "failed")
    else:
        await manager.cancel(task.task_id)

    first_terminal = await _next_type(first, f"task.{terminal_type}")
    second_terminal = await _next_type(second, f"task.{terminal_type}")
    assert first_terminal.task_id == second_terminal.task_id == task.task_id
    await first.aclose()
    await second.aclose()


@pytest.mark.asyncio
async def test_max_concurrent_enforced(manager):
    started = [asyncio.Event() for _ in range(4)]
    releases = [asyncio.Event() for _ in range(4)]

    async def make_worker(index):
        async def worker(_task, _ctx):
            started[index].set()
            await releases[index].wait()
            return str(index)

        return worker

    tasks = [await manager.create("writer", f"Task {index}") for index in range(4)]
    for index, task in enumerate(tasks):
        await manager.start_task(task.task_id, await make_worker(index))

    for event in started[:3]:
        await asyncio.wait_for(event.wait(), timeout=1)
    assert not started[3].is_set()
    assert (await manager.get(tasks[3].task_id)).status == "pending"

    releases[0].set()
    await asyncio.wait_for(started[3].wait(), timeout=1)
    assert (await manager.get(tasks[3].task_id)).status == "running"

    for release in releases[1:]:
        release.set()


@pytest.mark.asyncio
async def test_progress_is_monotonic_and_clamped(manager):
    task = await manager.create("writer", "Write a poem")
    events = manager.subscribe()
    await anext(events)

    async def worker(_task, ctx):
        for value in (-0.5, 0.6, 0.2, 1.5):
            await ctx.report_progress(value, str(value))
        return "Done"

    await manager.start_task(task.task_id, worker)
    progress_events = []
    while True:
        event = await asyncio.wait_for(anext(events), timeout=1)
        if event.type == "task.progress":
            progress_events.append(event.progress)
        if event.type == "task.done":
            break

    assert progress_events == [0.0, 0.6, 0.6, 1.0]
    assert progress_events == sorted(progress_events)
    await events.aclose()

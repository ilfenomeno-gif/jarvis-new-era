from __future__ import annotations

import asyncio

import pytest

from core.task_browser_pool import TaskBrowserPool
from core.task_workers import WorkerContext


def _context(task_id: str) -> WorkerContext:
    async def report(_progress: float, _message: str) -> None:
        return None

    return WorkerContext(
        task_id=task_id,
        role="browser",
        cancelled=asyncio.Event(),
        _report=report,
    )


@pytest.mark.asyncio
async def test_two_embedded_browsers_and_external_overflow():
    entered: dict[str, asyncio.Event] = {
        task_id: asyncio.Event() for task_id in ("one", "two")
    }
    release: dict[str, asyncio.Event] = {
        task_id: asyncio.Event() for task_id in ("one", "two")
    }
    external_urls: list[str] = []

    async def open_embedded(task_id, url, _ctx):
        entered[task_id].set()
        await release[task_id].wait()
        return f"read: {url}"

    def open_external(url):
        external_urls.append(url)

    pool = TaskBrowserPool(open_embedded, open_external)
    first = asyncio.create_task(pool.open_and_read("one", "https://one.test", _context("one")))
    second = asyncio.create_task(pool.open_and_read("two", "https://two.test", _context("two")))
    await asyncio.gather(*(event.wait() for event in entered.values()))

    overflow = await pool.open_and_read("three", "https://three.test", _context("three"))
    assert set(pool.active_task_ids) == {"one", "two"}
    assert external_urls == ["https://three.test"]
    assert overflow.endswith("https://three.test")

    release["one"].set()
    release["two"].set()
    assert await asyncio.gather(first, second) == [
        "read: https://one.test",
        "read: https://two.test",
    ]
    assert pool.active_task_ids == ()


@pytest.mark.asyncio
async def test_browser_slot_is_released_after_cancellation():
    entered = asyncio.Event()

    async def open_embedded(_task_id, _url, _ctx):
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    pool = TaskBrowserPool(open_embedded, lambda _url: None)
    task = asyncio.create_task(
        pool.open_and_read("one", "https://one.test", _context("one"))
    )
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert pool.active_task_ids == ()


@pytest.mark.asyncio
async def test_context_cancellation_stops_embedded_browser():
    entered = asyncio.Event()
    ctx = _context("one")

    async def open_embedded(_task_id, _url, _ctx):
        entered.set()
        await asyncio.Event().wait()
        return "unreachable"

    pool = TaskBrowserPool(open_embedded, lambda _url: None)
    task = asyncio.create_task(pool.open_and_read("one", "https://one.test", ctx))
    await asyncio.wait_for(entered.wait(), timeout=1)
    ctx.cancelled.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert pool.active_task_ids == ()


@pytest.mark.asyncio
async def test_external_opener_failure_is_not_hidden():
    entered = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()

    async def fail_external(_url):
        raise OSError("browser launch failed")

    async def open_embedded(task_id, _url, _ctx):
        entered[int(task_id)].set()
        await release.wait()
        return "embedded"

    pool = TaskBrowserPool(open_embedded, fail_external)
    first = asyncio.create_task(
        pool.open_and_read("0", "https://one.test", _context("0"))
    )
    second = asyncio.create_task(
        pool.open_and_read("1", "https://two.test", _context("1"))
    )
    await asyncio.gather(*(event.wait() for event in entered))

    with pytest.raises(OSError, match="browser launch failed"):
        await pool.open_and_read("3", "https://three.test", _context("3"))
    release.set()
    await asyncio.gather(first, second)

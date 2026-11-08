from __future__ import annotations

import asyncio

import pytest

from core.task_worker_impl import BrowserWorker, WriterWorker
from core.task_workers import WorkerContext


class _FakeLLM:
    def __init__(self, content: str = "Generated text"):
        self.content = content
        self.calls: list[dict] = []

    async def generate_text(self, prompt: str, **kwargs) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        return self.content


class _FakeBrowser:
    def __init__(self, result: str = "Example page"):
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def open_and_read(self, task_id, url, _ctx) -> str:
        self.calls.append((task_id, url))
        return self.result


def _context() -> tuple[WorkerContext, list[tuple[float, str]]]:
    progress: list[tuple[float, str]] = []

    async def report(value: float, message: str) -> None:
        progress.append((value, message))

    return (
        WorkerContext(
            task_id="a1b2c3",
            role="writer",
            cancelled=asyncio.Event(),
            _report=report,
        ),
        progress,
    )


@pytest.mark.asyncio
async def test_writer_generates_and_saves_task_text():
    llm = _FakeLLM()
    writes: list[tuple[str, str, str]] = []

    def file_writer(path: str, name: str, content: str) -> str:
        writes.append((path, name, content))
        return f"Written to: {name}"

    worker = WriterWorker(llm, file_writer=file_writer)
    ctx, progress = _context()
    result = await worker.run("Write a poem", ctx)

    assert llm.calls[0]["prompt"] == "Write a poem"
    assert llm.calls[0]["temperature"] == 0.8
    assert writes == [
        ("desktop/JARVIS Tasks", "jarvis-task-a1b2c3.txt", "Generated text")
    ]
    assert "Written to: jarvis-task-a1b2c3.txt" in result
    assert result.endswith("Generated text")
    assert [value for value, _ in progress] == [0.05, 0.85, 1.0]


@pytest.mark.asyncio
async def test_writer_propagates_file_write_failure():
    worker = WriterWorker(
        _FakeLLM(),
        file_writer=lambda _path, _name, _content: "Could not write file: denied",
    )
    ctx, _ = _context()

    with pytest.raises(RuntimeError, match="Could not write file: denied"):
        await worker.run("Write a poem", ctx)


@pytest.mark.asyncio
async def test_writer_cancels_llm_before_saving():
    entered = asyncio.Event()
    writes = []

    class BlockingLLM:
        async def generate_text(self, _prompt, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

    worker = WriterWorker(
        BlockingLLM(),
        file_writer=lambda *args: writes.append(args) or "Written to: file.txt",
    )
    ctx, _ = _context()
    task = asyncio.create_task(worker.run("Write a poem", ctx))
    await asyncio.wait_for(entered.wait(), timeout=1)
    ctx.cancelled.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert writes == []


@pytest.mark.asyncio
async def test_browser_worker_resolves_and_reads_a_page():
    llm = _FakeLLM("https://example.com\n")
    browser = _FakeBrowser("Example page contents")
    worker = BrowserWorker(llm, browser)
    ctx, progress = _context()

    result = await worker.run("open example", ctx)

    assert result == "Example page contents"
    assert browser.calls == [("a1b2c3", "https://example.com")]
    assert llm.calls[0]["system_instruction"] == worker._SYSTEM_INSTRUCTION
    assert progress[-1] == (1.0, "Pagina letta")


@pytest.mark.asyncio
async def test_browser_worker_passes_direct_url_without_llm():
    llm = _FakeLLM()
    browser = _FakeBrowser()
    worker = BrowserWorker(llm, browser)
    ctx, _ = _context()

    await worker.run("https://example.com/path", ctx)

    assert llm.calls == []
    assert browser.calls == [("a1b2c3", "https://example.com/path")]


@pytest.mark.parametrize(
    "value",
    ["javascript:alert(1)", "file:///C:/Windows/win.ini", "https://user:pass@example.com"],
)
def test_browser_worker_rejects_unsafe_urls(value):
    with pytest.raises(ValueError):
        BrowserWorker._normalize_url(value)

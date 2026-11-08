from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol
from urllib.parse import urlsplit

from actions.file_controller import write_file
from core.task_workers import WorkerContext

FileWriter = Callable[[str, str, str], str]


class _TextGenerator(Protocol):
    async def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float = 0.4,
    ) -> str: ...


class _BrowserBackend(Protocol):
    async def open_and_read(
        self, task_id: str, url: str, ctx: WorkerContext
    ) -> str: ...


async def _await_or_cancel(
    operation: Awaitable[str], ctx: WorkerContext
) -> str:
    if ctx.cancelled.is_set():
        raise asyncio.CancelledError
    work = asyncio.ensure_future(operation)
    cancellation = asyncio.create_task(ctx.cancelled.wait())
    try:
        done, _ = await asyncio.wait(
            (work, cancellation),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancellation in done:
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            raise asyncio.CancelledError
        return await work
    finally:
        if not work.done():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        cancellation.cancel()
        await asyncio.gather(cancellation, return_exceptions=True)


class WriterWorker:
    """Generate text in an isolated LLM call and save it as a task file."""

    role = "writer"
    tools = ["write_file"]
    timeout_seconds = 300.0
    _SYSTEM_INSTRUCTION = (
        "You are a silent writing worker. Produce only the requested content. "
        "Do not claim to have saved or sent anything."
    )

    def __init__(
        self,
        llm: _TextGenerator,
        *,
        output_directory: str = "desktop/JARVIS Tasks",
        file_writer: FileWriter | None = None,
    ):
        if not isinstance(output_directory, str) or not output_directory.strip():
            raise ValueError("output_directory must be non-empty text")
        self._llm = llm
        self._output_directory = output_directory.strip()
        self._file_writer = file_writer or self._write_file

    async def run(self, prompt: str, ctx: WorkerContext) -> str:
        await ctx.report_progress(0.05, "Preparazione del testo")
        content = await _await_or_cancel(
            self._llm.generate_text(
                prompt,
                system_instruction=self._SYSTEM_INSTRUCTION,
                temperature=0.8,
            ),
            ctx,
        )
        if ctx.cancelled.is_set():
            raise asyncio.CancelledError
        await ctx.report_progress(0.85, "Salvataggio del file")
        filename = f"jarvis-task-{ctx.task_id}.txt"
        outcome = self._file_writer(self._output_directory, filename, content)
        if not outcome.startswith("Written to:"):
            raise RuntimeError(outcome)
        await ctx.report_progress(1.0, "File pronto")
        return f"{outcome}\n\n{content}"

    @staticmethod
    def _write_file(path: str, name: str, content: str) -> str:
        return write_file(path=path, name=name, content=content)


class BrowserWorker:
    """Resolve a browsing request and delegate page work to the UI browser pool."""

    role = "browser"
    tools = ["embedded_browser", "read_page"]
    timeout_seconds = 180.0
    _SYSTEM_INSTRUCTION = (
        "Resolve the user's browser request to exactly one absolute HTTP or HTTPS "
        "URL. Return only that URL, without markdown or explanation."
    )

    def __init__(self, llm: _TextGenerator, browser: _BrowserBackend):
        self._llm = llm
        self._browser = browser

    async def run(self, prompt: str, ctx: WorkerContext) -> str:
        await ctx.report_progress(0.05, "Risoluzione della pagina")
        url = prompt.strip()
        if not self._is_http_url(url):
            url = await _await_or_cancel(
                self._llm.generate_text(
                    prompt,
                    system_instruction=self._SYSTEM_INSTRUCTION,
                    temperature=0.1,
                ),
                ctx,
            )
        url = self._normalize_url(url)
        await ctx.report_progress(0.2, "Apertura del browser")
        result = await _await_or_cancel(
            self._browser.open_and_read(ctx.task_id, url, ctx),
            ctx,
        )
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError("Browser worker returned no page result")
        await ctx.report_progress(1.0, "Pagina letta")
        return result.strip()

    @classmethod
    def _normalize_url(cls, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("Browser URL must be text")
        lines = value.strip().splitlines()
        if not lines:
            raise ValueError("Browser worker returned an empty URL")
        candidate = lines[0].strip().strip("`\"'")
        if not cls._is_http_url(candidate):
            raise ValueError("Browser worker must return an absolute HTTP or HTTPS URL")
        parsed = urlsplit(candidate)
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Browser URLs must not contain embedded credentials")
        return candidate

    @staticmethod
    def _is_http_url(value: str) -> bool:
        try:
            parsed = urlsplit(value.strip())
            return (
                parsed.scheme.lower() in {"http", "https"}
                and bool(parsed.hostname)
                and (parsed.port is None or 1 <= parsed.port <= 65535)
            )
        except ValueError:
            return False

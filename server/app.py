"""FastAPI entrypoint for the headless Jarvis task service."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.internal_workflow import default_database_path
from server.health import health_payload
from server.heartbeat import HeartbeatService
from server.queue import TaskQueue, TaskStatus

API_VERSION = "1.0"
LOGGER = logging.getLogger(__name__)


class TaskRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    created_at: str
    updated_at: str
    error: str = ""


def create_app(
    *,
    database_path: str | Path | None = None,
    task_handler=None,
    alert_callback=None,
    heartbeat_interval: float = 30,
    start_background: bool = True,
) -> FastAPI:
    db_path = Path(database_path) if database_path is not None else default_database_path()
    queue = TaskQueue(db_path, handler=task_handler)
    heartbeat = HeartbeatService(
        db_path,
        interval_seconds=heartbeat_interval,
        alert_callback=alert_callback,
    )
    worker_stop = threading.Event()
    worker_thread = threading.Thread(
        target=queue.worker_loop,
        kwargs={"stop_event": worker_stop},
        name="jarvis-server-task-worker",
        daemon=True,
    )
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=heartbeat.run,
        args=(heartbeat_stop,),
        name="jarvis-server-heartbeat",
        daemon=True,
    )
    started_at = time.monotonic()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if start_background:
            worker_thread.start()
            heartbeat_thread.start()
        try:
            yield
        finally:
            worker_stop.set()
            heartbeat_stop.set()
            if worker_thread.ident is not None:
                worker_thread.join(timeout=5.0)
            if heartbeat_thread.ident is not None:
                heartbeat_thread.join(timeout=5.0)
            if worker_thread.is_alive() or heartbeat_thread.is_alive():
                LOGGER.error("One or more server background threads did not stop cleanly.")

    app = FastAPI(title="Jarvis Headless Server", version=API_VERSION, lifespan=lifespan)
    app.state.task_queue = queue
    app.state.heartbeat = heartbeat
    app.state.started_at = started_at
    app.state.worker_thread = worker_thread
    app.state.worker_stop = worker_stop
    app.state.start_background = start_background

    @app.get("/health")
    def health() -> dict[str, str]:
        return health_payload()

    @app.get("/status")
    def status() -> dict[str, Any]:
        return {
            "status": "ok",
            "uptime_seconds": round(max(0.0, time.monotonic() - started_at), 3),
            "tasks": queue.counts(),
            "worker": {
                "running": worker_thread.is_alive(),
                "configured": start_background,
            },
            "heartbeat": heartbeat.status,
        }

    @app.post("/task", response_model=TaskResponse, status_code=202)
    def submit_task(request: TaskRequest) -> TaskResponse:
        try:
            item = queue.enqueue(request.task)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return TaskResponse(task_id=item.task_id, status=item.status)

    @app.get("/task/{task_id}", response_model=TaskStatusResponse)
    def get_task(task_id: str) -> TaskStatusResponse:
        item = queue.get(task_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return TaskStatusResponse(
            task_id=item.task_id,
            status=item.status,
            created_at=item.created_at,
            updated_at=item.updated_at,
            error=item.error,
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")

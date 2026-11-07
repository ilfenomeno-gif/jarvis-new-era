import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.heartbeat import HeartbeatService
from server.queue import TaskQueue


def test_queue_persists_task_and_recovers_it_after_restart(tmp_path):
    database = tmp_path / "server.sqlite3"
    first = TaskQueue(database)
    queued = first.enqueue("summarize the project")
    claimed = first.claim_next()

    assert claimed is not None and claimed.status == "running"
    restarted = TaskQueue(database)
    recovered = restarted.get(queued.task_id)

    assert recovered is not None
    assert recovered.status == "pending"
    assert recovered.task == "summarize the project"


def test_queue_worker_moves_pending_task_to_done(tmp_path):
    queue = TaskQueue(tmp_path / "server.sqlite3", handler=lambda task: {"result": task.upper()})
    queued = queue.enqueue("hello jarvis")

    assert queue.run_once()
    completed = queue.get(queued.task_id)
    assert completed is not None
    assert completed.status == "done"
    assert completed.result == {"result": "HELLO JARVIS"}
    assert not queue.run_once()


def test_queue_marks_handler_errors_failed_without_persisting_exception_details(tmp_path):
    queue = TaskQueue(
        tmp_path / "server.sqlite3",
        handler=lambda _task: (_ for _ in ()).throw(RuntimeError("secret token value")),
    )
    queued = queue.enqueue("run")

    assert queue.run_once()
    failed = queue.get(queued.task_id)
    assert failed is not None and failed.status == "failed"
    assert failed.error == "RuntimeError"
    assert "secret token value" not in failed.error


def test_queue_rejects_empty_or_oversized_tasks(tmp_path):
    queue = TaskQueue(tmp_path / "server.sqlite3")

    with pytest.raises(ValueError, match="non-empty"):
        queue.enqueue(" ")
    with pytest.raises(ValueError, match="20,000"):
        queue.enqueue("x" * 20_001)


def test_health_and_status_endpoints(tmp_path):
    app = create_app(database_path=tmp_path / "server.sqlite3", start_background=False)

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["tasks"] == {
        "pending": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
    }
    assert response.json()["worker"] == {"running": False, "configured": False}


def test_post_task_and_get_task_status(tmp_path):
    app = create_app(
        database_path=tmp_path / "server.sqlite3",
        task_handler=lambda task: {"echo": task},
        start_background=False,
    )

    with TestClient(app) as client:
        submitted = client.post("/task", json={"task": "draft a plan"})
        assert submitted.status_code == 202
        task_id = submitted.json()["task_id"]
        assert submitted.json()["status"] == "pending"
        pending = client.get(f"/task/{task_id}")
        assert pending.status_code == 200
        assert pending.json()["status"] == "pending"

        assert app.state.task_queue.run_once()
        done = client.get(f"/task/{task_id}")

    assert done.status_code == 200
    assert done.json()["status"] == "done"
    assert "result" not in done.json()


def test_post_task_validation_and_missing_task(tmp_path):
    app = create_app(database_path=tmp_path / "server.sqlite3", start_background=False)

    with TestClient(app) as client:
        assert client.post("/task", json={"task": " "}).status_code == 422
        assert client.post("/task", json={"text": "missing task field"}).status_code == 422
        assert client.get("/task/no-such-task").status_code == 404


def test_heartbeat_writes_sqlite_record(tmp_path):
    database = tmp_path / "heartbeat.sqlite3"
    heartbeat = HeartbeatService(database)

    recorded_at = heartbeat.record_once()

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT recorded_at, status FROM server_heartbeats"
        ).fetchone()
    assert row == (recorded_at, "ok")
    assert heartbeat.status == {"last_heartbeat": recorded_at, "last_error": None}


def test_heartbeat_failure_invokes_alert_callback(tmp_path, monkeypatch):
    alerts = []
    heartbeat = HeartbeatService(
        tmp_path / "heartbeat.sqlite3",
        interval_seconds=0.1,
        alert_callback=alerts.append,
    )
    monkeypatch.setattr(heartbeat, "record_once", lambda: (_ for _ in ()).throw(OSError("secret")))
    stop = threading.Event()
    thread = threading.Thread(target=heartbeat.run, args=(stop,), daemon=True)
    thread.start()
    deadline = time.monotonic() + 1
    while not alerts and time.monotonic() < deadline:
        time.sleep(0.01)
    stop.set()
    thread.join(timeout=1)

    assert alerts
    assert alerts[0]["type"] == "heartbeat_failure"
    assert alerts[0]["error"] == "OSError"
    assert "secret" not in str(alerts)


def test_app_background_worker_and_heartbeat_start_and_stop(tmp_path):
    app = create_app(
        database_path=tmp_path / "server.sqlite3",
        heartbeat_interval=0.1,
        start_background=True,
    )

    with TestClient(app) as client:
        submitted = client.post("/task", json={"task": "headless worker task"})
        task_id = submitted.json()["task_id"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            task = client.get(f"/task/{task_id}").json()
            if task["status"] == "done":
                break
            time.sleep(0.01)
        status = client.get("/status").json()

    assert task["status"] == "done"
    assert status["worker"]["configured"] is True
    with sqlite3.connect(tmp_path / "server.sqlite3") as connection:
        count = connection.execute("SELECT COUNT(*) FROM server_heartbeats").fetchone()[0]
    assert count >= 1

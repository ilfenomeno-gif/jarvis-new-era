import json
import logging
import threading
from datetime import UTC, datetime, timedelta

from core import log_reporter


def test_snapshot_counts_recent_records(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    entries = [
        {"timestamp": now.isoformat(), "severity": "ERROR"},
        {"timestamp": now.isoformat(), "severity": "CRITICAL"},
        {"timestamp": (now - timedelta(minutes=6)).isoformat(), "severity": "ERROR"},
    ]
    (tmp_path / "jarvis.session.jsonl").write_text(
        "\n".join(json.dumps(item) for item in entries), encoding="utf-8"
    )
    monkeypatch.setattr(log_reporter, "module_status", lambda: {"available": False, "active": [], "total": None})
    monkeypatch.setattr(log_reporter, "hardware_status", lambda: {"cpu": 1, "ram": 2, "disk": 3})
    snapshot = log_reporter.LogReporter(log_dir=tmp_path).get_snapshot()
    assert (snapshot["errors"], snapshot["critical"], snapshot["lines_last_minute"]) == (2, 1, 2)


def test_reporter_thread_stops():
    reporter = log_reporter.LogReporter(interval=10)
    reporter.start()
    reporter.stop()
    reporter.join(timeout=1)
    assert not reporter.is_alive()


def test_invalid_records_are_reported(tmp_path, caplog):
    (tmp_path / "jarvis.session.jsonl").write_text("invalid\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert log_reporter.recent_records(5, tmp_path) == []
    assert "Riga JSONL non valida" in caplog.text


def test_module_status_does_not_start_hub(monkeypatch):
    from core import symbiosis_hub

    hub = symbiosis_hub.SymbiosisHub(modules={"pulse", "network"})
    hub._modules["pulse"] = object()
    monkeypatch.setattr(symbiosis_hub, "get_symbiosis_hub", lambda *, start: hub if not start else None)
    assert log_reporter.module_status() == {"available": True, "active": ["pulse"], "total": 2}


def test_periodic_snapshot_and_singleton(monkeypatch, caplog):
    reporter = log_reporter.LogReporter(interval=0.01)
    event = threading.Event()
    monkeypatch.setattr(reporter, "get_snapshot", lambda: {
        "modules": {"available": True, "active": ["pulse"], "total": 1},
        "hardware": {"cpu": 3, "ram": 4}, "critical": 0, "lines_last_minute": 2,
    })
    with caplog.at_level(25):
        reporter.start()
        for _ in range(100):
            if "Snapshot:" in caplog.text:
                event.set()
                break
            event.wait(0.01)
        reporter.stop()
        reporter.join(timeout=1)
    assert "1/1 moduli attivi" in caplog.text
    monkeypatch.setattr(log_reporter, "_reporter", None)
    first = log_reporter.start_reporter()
    assert log_reporter.start_reporter() is first
    first.stop()
    first.join(timeout=1)

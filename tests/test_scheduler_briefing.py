from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core.scheduler import Scheduler


def test_reminder_persisted_reloaded_and_fired_once(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "scheduled_tasks.json"
    scheduler = Scheduler(path)
    task = scheduler.add("reminder", "bere", "once", delay_minutes=10, now=now)
    reloaded = Scheduler(path)
    delivered = []
    reloaded._callback = delivered.append
    reloaded.run_due(now + timedelta(minutes=9))
    assert not delivered
    reloaded.run_due(now + timedelta(minutes=10))
    reloaded.run_due(now + timedelta(minutes=11))
    assert delivered == [task]
    assert Scheduler(path).list_tasks() == []


def test_daily_and_interval_reschedule(tmp_path):
    now = datetime.now().astimezone()
    scheduler = Scheduler(tmp_path / "tasks.json")
    daily = scheduler.add("weather", "", "daily", hour=8, minute=0, now=now)
    interval = scheduler.add("briefing", "", "interval", delay_minutes=10, now=now)
    delivered = []
    scheduler._callback = delivered.append
    run_at = max(datetime.fromisoformat(daily["next_run"]),
                 datetime.fromisoformat(interval["next_run"]))
    scheduler.run_due(run_at)
    assert {item["id"] for item in delivered} == {daily["id"], interval["id"]}
    assert all(datetime.fromisoformat(item["next_run"]) > run_at for item in scheduler.list_tasks())


def test_failed_dispatch_remains_persisted(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "tasks.json"
    scheduler = Scheduler(path)
    task = scheduler.add("reminder", "bere", "once", delay_minutes=1, now=now)

    def fail(_task):
        raise RuntimeError("offline")

    scheduler._callback = fail
    scheduler.run_due(now + timedelta(minutes=1))
    assert Scheduler(path).list_tasks() == [task]


def test_invalid_tasks_rejected(tmp_path):
    scheduler = Scheduler(tmp_path / "tasks.json")
    with pytest.raises(ValueError):
        scheduler.add("terminal", "format C:", "once", delay_minutes=1)
    with pytest.raises(ValueError):
        scheduler.add("reminder", "", "once", delay_minutes=1)
    with pytest.raises(ValueError):
        scheduler.add("weather", "", "daily", hour=25)


def test_briefing_combines_weather_news_and_tasks(monkeypatch):
    from actions import morning_briefing
    from actions import web_search
    from memory import memory_manager

    monkeypatch.setattr(memory_manager, "load_memory", lambda: {"identity": {"city": {"value": "Roma"}}})
    monkeypatch.setattr(web_search, "_ddg_search", lambda *_a, **_kw: [{"snippet": "Sole, 20 gradi."}])
    monkeypatch.setattr(web_search, "_ddg_news", lambda *_a, **_kw: [{"title": f"Titolo {n}"} for n in range(1, 5)])
    monkeypatch.setattr(web_search, "_run_bounded", lambda fn, **_kwargs: fn())
    task = {"next_run": datetime.now().astimezone().isoformat(), "message": "bere", "kind": "reminder"}
    monkeypatch.setattr(morning_briefing, "get_scheduler", lambda: SimpleNamespace(list_tasks=lambda: [task]))
    result = morning_briefing.morning_briefing()
    assert all(value in result for value in ["Roma", "Sole", "Titolo 1", "Titolo 2", "Titolo 3", "bere"])
    assert "Titolo 4" not in result
    assert "calendario esterno non è incluso" in result


def test_schedule_action_uses_shared_scheduler(monkeypatch, tmp_path):
    from actions import schedule_task
    scheduler = Scheduler(tmp_path / "tasks.json")
    monkeypatch.setattr(schedule_task, "get_scheduler", lambda: scheduler)
    result = schedule_task.schedule_task({"kind": "reminder", "message": "bere", "schedule": "once", "delay_minutes": 10})
    assert "Task pianificato" in result
    assert scheduler.list_tasks()[0]["message"] == "bere"


def test_scheduled_reminder_reaches_ui_and_voice():
    import threading
    from main import JarvisLive

    done = threading.Event()
    logs, spoken = [], []
    live = object.__new__(JarvisLive)
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(write_log=logs.append)
    live._hud = SimpleNamespace(push_chat=lambda *_args: None)
    live.session = object()
    live._loop = object()

    def speak(message):
        spoken.append(message)
        done.set()

    live.speak = speak
    live._deliver_scheduled_task({"kind": "reminder", "message": "bere"})
    assert done.wait(2)
    assert any("Promemoria, Signore: bere" in item for item in logs)
    assert spoken[0].endswith("Promemoria, Signore: bere")


def test_background_scheduler_processes_due_task(tmp_path):
    import threading

    now = datetime.now(timezone.utc)
    path = tmp_path / "tasks.json"
    scheduler = Scheduler(path)
    scheduler.add("reminder", "bere", "once", delay_minutes=1, now=now - timedelta(minutes=2))
    received = []
    done = threading.Event()
    scheduler.start(lambda task: (received.append(task), done.set()))
    try:
        assert done.wait(2)
    finally:
        scheduler.stop()
    assert received[0]["message"] == "bere"
    assert Scheduler(path).list_tasks() == []


def test_new_actions_are_discoverable_and_routed():
    from pathlib import Path
    from core.action_loader import discover_actions
    from core.tool_router import ToolRouter

    registry = discover_actions(Path(__file__).resolve().parents[1] / "actions",
                                logger=lambda _message: None)
    assert registry.has("schedule_task")
    assert registry.has("morning_briefing")
    declarations = registry.get_tool_declarations()
    router = ToolRouter()
    for text, expected in [
        ("tra 10 minuti ricordami di bere", "schedule_task"),
        ("ogni mattina alle 8 dimmi il meteo", "schedule_task"),
        ("briefing mattutino", "morning_briefing"),
        ("esegui ipconfig", "terminal_run"),
    ]:
        selected = router.select(text, declarations)
        assert expected in {item["name"] for item in selected}

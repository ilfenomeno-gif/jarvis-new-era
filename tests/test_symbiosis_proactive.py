import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace

import pytest

from core.ambient_presence import AmbientPresence
from core.proactive_engine import ProactiveEngine
from main import JarvisLive
from memory import memory_manager


def build(monkeypatch, tmp_path, presence="focus"):
    monkeypatch.setattr(memory_manager, "USER_PROFILE_PATH", tmp_path / "profile.json")
    clock = [0.0]
    context = SimpleNamespace(value={
        "window_category": "relax", "idle_minutes": 0, "locked": False,
        "calendar": {"status": "free"}, "symbiosis": {"pulse": {}, "process": {}, "network": {}, "monitor": {}},
    })
    context.get_context = lambda: context.value
    ambient = AmbientPresence(context, clock=lambda: clock[0])
    if presence == "focus":
        ambient.set_mode("focus")
    events = []
    engine = ProactiveEngine(context, lambda event: events.append(event) or True,
                             clock=lambda: clock[0], wall_clock=lambda: clock[0],
                             now=lambda: datetime(2026, 1, 1, 10), ambient=ambient)
    return engine, context.value["symbiosis"], clock, ambient


def pulse_sample(state, clock, **values):
    state["pulse"].update(sampled_at_monotonic=clock[0], fresh_for_seconds=10, **values)


def hog_sample(state, clock, *, duration, identity="first"):
    state["process"]["hog"] = {
        "name": "chrome.exe", "cpu_percent": 95, "identity": identity,
        "observed_at": clock[0], "fresh_for_seconds": 20,
        "cpu_high_for_seconds": duration,
    }


def network_sample(state, clock, **values):
    state["network"].update(sampled_at_monotonic=clock[0], fresh_for_seconds=60, **values)


def deliver(engine, ambient, event):
    sent, ui = [], []

    async def send_client_content(**kwargs):
        sent.append(kwargs)

    live = SimpleNamespace(_proactive=engine, _ambient=ambient,
                           _hud=SimpleNamespace(push_chat=lambda *args: ui.append(args)),
                           ui=SimpleNamespace(write_log=lambda _: None, muted=False),
                           session=SimpleNamespace(send_client_content=send_client_content),
                           _speaking_lock=threading.Lock(), _is_speaking=False,
                           _session_ready_event=threading.Event(), _task_idle_event=threading.Event(),
                           _last_user_speech=-1000000, _set_task_idle=lambda _: None)
    live._session_ready_event.set()
    live._task_idle_event.set()
    asyncio.run(JarvisLive._deliver_proactive_event(live, event))
    return sent, ui


def test_sustained_cpu_in_focus_only_uses_ui(monkeypatch, tmp_path):
    engine, state, clock, ambient = build(monkeypatch, tmp_path)
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=0)
    assert engine.tick() is None
    clock[0] = 119
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=119)
    assert engine.tick() is None
    clock[0] = 120
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=120)
    event = engine.tick()
    assert event.kind == "high_cpu"
    sent, ui = deliver(engine, ambient, event)
    assert ui and not sent
    assert engine.tick() is None


def test_cpu_condition_must_remain_over_threshold_and_takes_priority(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    pulse_sample(state, clock, cpu_percent=90, cpu_sustained_seconds=0)
    assert engine.tick() is None
    clock[0] = 120
    assert engine.tick() is None
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=0)
    assert engine.tick() is None
    clock[0] = 240
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=120)
    engine._context.value["calendar"] = {"status": "upcoming", "minutes": 5, "start": "tomorrow"}
    assert engine.tick().kind == "high_cpu"


def test_battery_in_available_is_voiced_and_preference_disables(monkeypatch, tmp_path):
    from core.bidirectional_learning import learn

    engine, state, clock, ambient = build(monkeypatch, tmp_path, "available")
    pulse_sample(state, clock, battery_percent=10, battery_plugged=False)
    event = engine.tick()
    assert event.kind == "low_battery"
    sent, ui = deliver(engine, ambient, event)
    assert sent and not ui
    learn("Non avvisarmi della batteria")
    engine._last_sent = None
    engine._seen.clear()
    assert engine.tick() is None


def test_network_drop_and_hog_sustain(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    network_sample(state, clock, connected=True)
    assert engine.tick() is None
    network_sample(state, clock, connected=False)
    event = engine.tick()
    assert event.kind == "network_drop"
    engine.complete(event, delivered=True)
    engine._last_sent = None
    hog_sample(state, clock, duration=0)
    assert engine.tick() is None
    clock[0] = 180
    hog_sample(state, clock, duration=180)
    event = engine.tick()
    assert event.kind == "hog_alert"
    assert "chrome.exe" in event.detail


def test_unknown_wifi_signal_does_not_trigger(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    network_sample(state, clock, wifi_signal_percent=-1, wifi_weak_seconds=300)
    assert engine.tick() is None
    clock[0] = 300
    assert engine.tick() is None


def test_wifi_requires_fresh_continuous_samples(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    network_sample(state, clock, wifi_signal_percent=20, wifi_weak_seconds=120)
    clock[0] = 61
    assert engine.tick() is None
    network_sample(state, clock, wifi_signal_percent=20, wifi_weak_seconds=0)
    assert engine.tick() is None
    clock[0] += 120
    network_sample(state, clock, wifi_signal_percent=20, wifi_weak_seconds=120)
    assert engine.tick().kind == "wifi_weak"


def test_hog_requires_same_process_identity(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    hog_sample(state, clock, duration=0)
    assert engine.tick() is None
    clock[0] = 179
    hog_sample(state, clock, duration=0, identity="second")
    assert engine.tick() is None
    clock[0] = 180
    hog_sample(state, clock, duration=1, identity="second")
    assert engine.tick() is None
    clock[0] = 359
    hog_sample(state, clock, duration=180, identity="second")
    assert engine.tick().kind == "hog_alert"


@pytest.mark.parametrize(("field", "boundary", "crossed", "kind"), [
    ("ram_percent", 85, 85.01, "high_ram"),
    ("disk_free_gb", 5, 4.99, "low_disk"),
    ("temperature_c", 85, 85.01, "high_temp"),
])
def test_hardware_thresholds_are_strict(monkeypatch, tmp_path, field, boundary, crossed, kind):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    pulse_sample(state, clock, **{field: boundary})
    assert engine.tick() is None
    state["pulse"][field] = crossed
    assert engine.tick().kind == kind


def test_stale_and_interrupted_hardware_samples_cannot_trigger(monkeypatch, tmp_path):
    engine, state, clock, _ = build(monkeypatch, tmp_path)
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=120, battery_percent=10,
                 battery_plugged=False)
    hog_sample(state, clock, duration=180)
    clock[0] = 21
    assert engine.tick() is None

    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=0, battery_percent=None)
    hog_sample(state, clock, duration=0)
    assert engine.tick() is None
    clock[0] += 1
    pulse_sample(state, clock, cpu_percent=95, cpu_sustained_seconds=1)
    hog_sample(state, clock, duration=1)
    assert engine.tick() is None

import importlib
import json
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actions import _system_pulse_action_helpers as action_helpers
from actions import system_pulse as pulse_action
from core import system_pulse as pulse_module
from core.action_loader import discover_actions
from core.system_pulse import SystemPulse


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def test_snapshot_handles_unavailable_and_invalid_metrics(monkeypatch):
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: float("nan"))
    monkeypatch.setattr(
        pulse_module.psutil, "virtual_memory",
        lambda: SimpleNamespace(percent=float("inf"), used=-1, total=100),
    )
    monkeypatch.setattr(pulse_module.psutil, "pids", lambda: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(pulse_module.psutil, "boot_time", lambda: (_ for _ in ()).throw(OSError()))

    metrics = SystemPulse().sample_once()

    assert metrics["cpu_percent"] is None
    assert metrics["memory_percent"] is None
    assert metrics["memory_used_bytes"] is None
    assert metrics["memory_total_bytes"] == 100
    assert metrics["process_count"] is None
    assert metrics["uptime_seconds"] is None
    metrics["cpu_percent"] = 1
    assert SystemPulse().snapshot()["cpu_percent"] is None


def test_disk_enumeration_error_is_not_an_empty_success_and_is_logged(monkeypatch, caplog):
    def fail(**_kwargs):
        raise OSError("SECRET_PATH")

    monkeypatch.setattr(pulse_module.psutil, "disk_partitions", fail)
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        snapshot = SystemPulse().sample_once()

    assert snapshot["disks"] is None
    assert snapshot["disk_count"] is None
    assert snapshot["disk_total_bytes"] is None
    assert "[SYMBIOSIS][PULSE] Enumerazione dischi non riuscita" in caplog.text
    assert "SECRET_PATH" not in caplog.text


@pytest.mark.parametrize("percent", [None, float("nan"), -1, 101])
def test_invalid_disk_percent_is_none_not_zero(monkeypatch, caplog, percent):
    monkeypatch.setattr(
        pulse_module.psutil, "disk_partitions",
        lambda **_: [SimpleNamespace(device="secret", mountpoint="secret")],
    )
    monkeypatch.setattr(
        pulse_module.psutil, "disk_usage",
        lambda _: SimpleNamespace(total=100, used=50, free=50, percent=percent),
    )
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        snapshot = SystemPulse().sample_once()

    assert snapshot["disks"][0]["percent"] is None
    assert "[SYMBIOSIS][PULSE] Percentuale disco non valida" in caplog.text


def test_disk_read_error_keeps_partial_record_without_partial_aggregate(monkeypatch, caplog):
    monkeypatch.setattr(
        pulse_module.psutil, "disk_partitions",
        lambda **_: [
            SimpleNamespace(device="one", mountpoint="one"),
            SimpleNamespace(device="two", mountpoint="SECRET_PATH"),
        ],
    )

    def usage(path):
        if path == "SECRET_PATH":
            raise PermissionError("SECRET_PATH")
        return SimpleNamespace(total=100, used=50, free=50, percent=50)

    monkeypatch.setattr(pulse_module.psutil, "disk_usage", usage)
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        snapshot = SystemPulse().sample_once()
    assert snapshot["disk_count"] == 2
    assert snapshot["disks"][1]["percent"] is None
    assert snapshot["disk_total_bytes"] is None
    assert snapshot["disk_percent"] is None
    assert "[SYMBIOSIS][PULSE] Lettura disco non riuscita" in caplog.text
    assert "SECRET_PATH" not in caplog.text


def test_non_gpu_read_failures_are_logged_without_leaking_details(monkeypatch, caplog):
    def fail(*_args, **_kwargs):
        raise OSError("SECRET_PATH")

    for name in ("cpu_percent", "virtual_memory", "sensors_battery",
                 "net_io_counters", "pids", "boot_time"):
        monkeypatch.setattr(pulse_module.psutil, name, fail)
    monkeypatch.setattr(pulse_module.psutil, "sensors_temperatures", fail, raising=False)
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        snapshot = SystemPulse().sample_once()

    for field in ("cpu_percent", "cpu_cores_percent", "memory_percent", "battery_percent",
                  "network_up_mb_s", "process_count", "uptime_seconds"):
        assert snapshot[field] is None
    for phrase in ("Lettura CPU", "Lettura core CPU", "Lettura memoria",
                   "Lettura batteria", "Lettura contatori rete", "Lettura processi",
                   "Lettura uptime", "Lettura temperature"):
        assert f"[SYMBIOSIS][PULSE] {phrase}" in caplog.text
    assert "SECRET_PATH" not in caplog.text


def test_optional_gpu_failures_remain_silent(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setitem(sys.modules, "GPUtil", None)
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        result = SystemPulse._read_gpu()
    assert all(value is None for value in result.values())
    assert not caplog.records


def test_unexpected_worker_error_logs_and_clears_stale_snapshot(monkeypatch, caplog):
    pulse = SystemPulse(interval=0.01)
    sampled = threading.Event()

    def fail():
        sampled.set()
        raise RuntimeError("SECRET_PATH")

    monkeypatch.setattr(pulse, "sample_once", fail)
    with caplog.at_level("WARNING", logger="core.system_pulse"):
        pulse.start()
        try:
            assert sampled.wait(1)
            deadline = time.monotonic() + 1
            while pulse.snapshot()["cpu_threshold_percent"] is not None:
                assert time.monotonic() < deadline
                time.sleep(0.005)
            snapshot = pulse.snapshot()
        finally:
            pulse.stop()
    assert snapshot["cpu_percent"] is None
    assert snapshot["disks"] is None
    assert snapshot["trend_60"]["metrics"]["cpu_percent"]["direction"] is None
    assert "[SYMBIOSIS][PULSE] Campionamento non riuscito" in caplog.text
    assert "SECRET_PATH" not in caplog.text


def test_sustained_cpu_requires_threshold_continuity(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 95)
    pulse = SystemPulse(cpu_threshold=90, cpu_sustain_seconds=10, clock=clock)

    assert not pulse.sample_once()["cpu_sustained"]
    clock.value = 9.9
    assert not pulse.sample_once()["cpu_sustained"]
    clock.value = 10
    assert pulse.sample_once()["cpu_sustained"]
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 25)
    assert not pulse.sample_once()["cpu_sustained"]
    assert pulse.snapshot()["cpu_sustained_seconds"] == 0


def test_sample_timestamp_is_not_refreshed_by_snapshot_reads(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 95)
    pulse = SystemPulse(clock=clock)
    assert pulse.get_pulse()["sampled_at_monotonic"] is None
    clock.value = 12.5
    assert pulse.sample_once()["sampled_at_monotonic"] == 12.5
    clock.value = 100
    assert pulse.get_pulse()["sampled_at_monotonic"] == 12.5
    assert pulse.snapshot()["cpu_sustained_seconds"] == 0
    assert pulse.sample_once()["sampled_at_monotonic"] == 100


def test_utc_timestamp_is_captured_per_sample_and_stable_on_reads(monkeypatch):
    class FakeDateTime:
        current = datetime(2026, 11, 12, 22, 30, tzinfo=UTC)

        @classmethod
        def now(cls, tz):
            assert tz == UTC
            return cls.current

    monkeypatch.setattr(pulse_module, "datetime", FakeDateTime)
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 95)
    pulse = SystemPulse(clock=Clock())
    assert pulse.snapshot()["timestamp"] is None
    result = pulse.sample_once()
    assert datetime.fromisoformat(result["timestamp"]) == FakeDateTime.current
    assert datetime.fromisoformat(result["timestamp"]).utcoffset() == timedelta(0)
    FakeDateTime.current += timedelta(seconds=5)
    assert pulse.get_pulse()["timestamp"] == result["timestamp"]
    assert pulse.snapshot()["timestamp"] == result["timestamp"]
    assert datetime.fromisoformat(pulse.sample_once()["timestamp"]) == FakeDateTime.current


def test_timestamp_tracks_cpu_sampling_not_completion(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 95)

    def slow_memory():
        clock.value += 3
        return SimpleNamespace(percent=50, used=5, total=10)

    monkeypatch.setattr(pulse_module.psutil, "virtual_memory", slow_memory)
    pulse = SystemPulse(clock=clock)
    clock.value = 10
    result = pulse.sample_once()
    assert clock.value == 13
    assert result["sampled_at_monotonic"] == 10
    clock.value = 15
    assert pulse.sample_once()["cpu_sustained_seconds"] == 5


def test_default_cpu_sustained_needs_full_two_minutes(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 91)
    pulse = SystemPulse(clock=clock)
    for tick in range(24):
        clock.value = tick * 5
        assert pulse.sample_once()["cpu_sustained"] is False
    clock.value = 120
    assert pulse.sample_once()["cpu_sustained"] is True


def test_cpu_sustained_gap_strict_threshold_and_recovery(monkeypatch):
    clock = Clock()
    cpu = {"value": 91}
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: cpu["value"])
    pulse = SystemPulse(interval=5, cpu_threshold=90, cpu_sustain_seconds=10, clock=clock)

    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    clock.value = 10
    assert pulse.sample_once()["cpu_sustained"] is True
    clock.value = 20.001
    result = pulse.sample_once()
    assert result["sampled_at_monotonic"] == 20.001
    assert result["cpu_sustained_seconds"] == 0
    assert result["cpu_sustained"] is False
    clock.value = 25.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == pytest.approx(5)
    clock.value = 30.001
    assert pulse.sample_once()["cpu_sustained"] is True
    cpu["value"] = 90
    clock.value = 35.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    cpu["value"] = 91
    clock.value = 40.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    cpu["value"] = float("nan")
    clock.value = 45.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    cpu["value"] = 91
    clock.value = 50.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    clock.value = 55.001
    assert pulse.sample_once()["cpu_sustained_seconds"] == pytest.approx(5)


def test_cpu_sustained_resets_on_clock_regression_and_stop(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 95)
    pulse = SystemPulse(interval=5, clock=clock)
    clock.value = 10
    pulse.sample_once()
    clock.value = 5
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0
    clock.value = 10
    assert pulse.sample_once()["cpu_sustained_seconds"] == 5
    assert pulse.stop()
    clock.value = 15
    assert pulse.sample_once()["cpu_sustained_seconds"] == 0


def test_default_interval_and_sustained_cpu_duration():
    pulse = SystemPulse()
    assert pulse.interval == 5.0
    assert pulse.cpu_sustain_seconds == 120.0


def test_collects_privacy_filtered_core_disks_battery_and_network(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(
        pulse_module.psutil, "cpu_percent",
        lambda **kwargs: [20, 60] if kwargs.get("percpu") else 40,
    )
    monkeypatch.setattr(
        pulse_module.psutil, "virtual_memory",
        lambda: SimpleNamespace(percent=50, used=500, total=1000),
    )
    monkeypatch.setattr(
        pulse_module.psutil, "disk_partitions",
        lambda **_: [
            SimpleNamespace(device="SECRET_DEVICE", mountpoint="SECRET_PATH"),
            SimpleNamespace(device="SECRET_DEVICE", mountpoint="SECRET_PATH"),
        ],
    )
    monkeypatch.setattr(
        pulse_module.psutil, "disk_usage",
        lambda _: SimpleNamespace(total=1000, used=400, free=600, percent=40),
    )
    monkeypatch.setattr(
        pulse_module.psutil, "sensors_battery",
        lambda: SimpleNamespace(percent=75, power_plugged=True, secsleft=3600),
    )
    monkeypatch.setattr(pulse_module.psutil, "sensors_temperatures", lambda: {
        "coretemp": [SimpleNamespace(current=55.5)],
        "secret_sensor_name": [SimpleNamespace(current=99)],
    }, raising=False)
    counters = iter([
        SimpleNamespace(bytes_recv=1000, bytes_sent=2000),
        SimpleNamespace(bytes_recv=1200, bytes_sent=2300),
    ])
    monkeypatch.setattr(pulse_module.psutil, "net_io_counters", lambda **_: next(counters))
    monkeypatch.setattr(pulse_module.psutil, "pids", lambda: [1, 2])
    monkeypatch.setattr(pulse_module.psutil, "boot_time", lambda: 90)
    monkeypatch.setattr(pulse_module.time, "time", lambda: 100)
    monkeypatch.setattr(pulse_module.SystemPulse, "_read_gpu", classmethod(
        lambda cls: {
            "gpu_percent": 20.0, "gpu_memory_percent": 10.0,
            "gpu_memory_used_bytes": 100, "gpu_memory_total_bytes": 1000,
        }
    ))
    pulse = SystemPulse(clock=clock)

    first = pulse.sample_once()
    clock.value = 5
    second = pulse.sample_once()

    assert first["disk_count"] == 1
    assert first["disk_percent"] == 40
    assert first["battery_percent"] == 75
    assert first["battery_plugged"] is True
    assert first["temperature_celsius"] == 55.5
    assert second["network_received_bytes_per_second"] == 40
    assert second["network_sent_bytes_per_second"] == 60
    assert second["network_download_mb_s"] == 0.00004
    assert second["network_upload_mb_s"] == 0.00006
    assert second["network_down_mb_s"] == 0.00004
    assert second["network_up_mb_s"] == 0.00006
    assert second["cpu_cores_percent"] == [20, 60]
    assert second["gpu_percent"] == 20
    assert second["process_count"] == 2
    assert second["uptime_seconds"] == 10
    assert second["trend_60"]["sample_count"] == 2
    assert second["trend_60"]["metrics"]["cpu_percent"] == {
        "min": 40, "average": 40, "max": 40, "change": 0,
        "direction": "stable",
    }
    serialized = json.dumps(second)
    assert "SECRET_DEVICE" not in serialized
    assert "SECRET_PATH" not in serialized
    assert "secret_sensor_name" not in serialized


def test_trend_window_is_bounded_to_sixty_samples(monkeypatch):
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: 10)
    pulse = SystemPulse(clock=Clock())
    for _ in range(75):
        pulse.sample_once()
        pulse._clock.value += 1
    trend = pulse.snapshot()["trend_60"]
    assert trend["sample_count"] == 60
    assert trend["window_seconds"] == 59


@pytest.mark.parametrize(
    ("samples", "direction"),
    [
        ([10, 25], "rising"),
        ([25, 10], "falling"),
        ([10, 10.5], "stable"),
    ],
)
def test_get_trend_classifies_rising_falling_and_stable(samples, direction, monkeypatch):
    readings = iter(samples)
    monkeypatch.setattr(
        pulse_module.psutil, "cpu_percent",
        lambda **kwargs: [0] if kwargs.get("percpu") else next(readings),
    )
    clock = Clock()
    pulse = SystemPulse(clock=clock)
    pulse.sample_once()
    clock.value = 5
    pulse.sample_once()

    assert pulse.get_trend("cpu_percent") == direction
    assert pulse.snapshot()["trend_60"]["metrics"]["cpu_percent"]["direction"] == direction


def test_get_trend_rejects_unknown_or_unavailable_metrics():
    pulse = SystemPulse()
    with pytest.raises(ValueError, match="Unknown trend metric"):
        pulse.get_trend("not_a_metric")
    with pytest.raises(ValueError, match="Trend unavailable"):
        pulse.get_trend("cpu_percent")


def test_module_get_trend_returns_string(monkeypatch):
    class FakePulse:
        def start(self):
            raise AssertionError("Getter must not start a collector")

        def get_trend(self, metric):
            assert metric == "cpu_percent"
            return "rising"

    monkeypatch.setattr(pulse_module, "get_system_pulse", FakePulse)
    assert pulse_module.get_trend("cpu_percent") == "rising"


@pytest.mark.parametrize("state", ["disabled", "inactive", "unselected"])
def test_module_getters_require_active_hub_and_selected_pulse(monkeypatch, state):
    import core.symbiosis_hub as hub_module

    hub_module.stop_symbiosis_hub()
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "0" if state == "disabled" else "1")
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", "")
    if state == "unselected":
        hub_module.get_symbiosis_hub()
    try:
        for getter in (
            pulse_module.get_system_pulse,
            pulse_module.get_pulse,
            lambda: pulse_module.get_trend("cpu_percent"),
        ):
            with pytest.raises(RuntimeError, match=(
                "pulse" if state == "unselected" else "SymbiosisHub"
            )):
                getter()
        if state != "unselected":
            assert hub_module._hub is None
    finally:
        hub_module.stop_symbiosis_hub()


def test_module_getters_reuse_hub_collector_without_starting_it(monkeypatch):
    import core.symbiosis_hub as hub_module

    class FakePulse:
        starts = 0

        def start(self):
            self.starts += 1

        def stop(self, timeout=0):
            return True

        def get_pulse(self):
            return {"cpu_percent": 25}

        def get_trend(self, metric):
            assert metric == "cpu_percent"
            return "stable"

    hub_module.stop_symbiosis_hub()
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "1")
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", "pulse")
    pulse = FakePulse()
    monkeypatch.setattr(hub_module.SymbiosisHub, "_create", staticmethod(lambda _: pulse))
    try:
        hub_module.get_symbiosis_hub()
        assert pulse_module.get_system_pulse() is pulse
        assert pulse_module.get_pulse() == {"cpu_percent": 25}
        assert pulse_module.get_trend("cpu_percent") == "stable"
        assert pulse.starts == 1
        monkeypatch.setenv("JARVIS_SYMBIOSIS", "0")
        with pytest.raises(RuntimeError, match="SymbiosisHub"):
            pulse_module.get_system_pulse()
        assert pulse.starts == 1
    finally:
        hub_module.stop_symbiosis_hub()


def test_gputil_fallback_returns_only_usage_and_vram(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynvml", None)
    monkeypatch.setitem(
        sys.modules, "GPUtil",
        SimpleNamespace(getGPUs=lambda: [
            SimpleNamespace(load=0.25, memoryUsed=512, memoryTotal=2048, id=7,
                             name="PRIVATE_GPU_NAME")
        ]),
    )

    gpu = SystemPulse._read_gpu()

    assert gpu == {
        "gpu_percent": 25.0,
        "gpu_memory_percent": 25.0,
        "gpu_memory_used_bytes": 512 * 1024**2,
        "gpu_memory_total_bytes": 2048 * 1024**2,
    }


def test_collector_starts_idempotently_samples_and_stops(monkeypatch):
    sampled = threading.Event()
    monkeypatch.setattr(pulse_module.psutil, "cpu_percent", lambda **_: sampled.set() or 15)
    monkeypatch.setattr(
        pulse_module.psutil, "virtual_memory",
        lambda: SimpleNamespace(percent=30, used=3, total=10),
    )
    pulse = SystemPulse(interval=0.01)

    pulse.start()
    pulse.start()
    try:
        assert sampled.wait(1)
        deadline = time.monotonic() + 1
        while pulse.snapshot()["cpu_percent"] is None and time.monotonic() < deadline:
            time.sleep(0.005)
        assert pulse.is_running
        assert pulse.snapshot()["cpu_percent"] == 15
    finally:
        assert pulse.stop()

    assert not pulse.is_running
    assert pulse.stop()


def test_action_exposes_read_only_json_snapshot(monkeypatch):
    snapshot = {"cpu_percent": 12.5, "cpu_sustained": False}
    pulse = SimpleNamespace(snapshot=lambda: snapshot)
    hub = SimpleNamespace(get_module=lambda name: pulse if name == "pulse" else None)
    monkeypatch.setattr(action_helpers, "get_symbiosis_hub", lambda **_: hub)

    assert pulse_action.TOOL["name"] == "system_pulse"
    assert pulse_action.TOOL["risk_class"] == "read"
    assert json.loads(pulse_action.system_pulse({})) == {
        "cpu_percent": 12.5, "cpu_sustained": False,
    }


@pytest.mark.parametrize(
    ("module_name", "tool_name", "keys"),
    [
        ("actions.check_battery", "check_battery",
         {"battery_percent", "battery_plugged", "battery_seconds_left"}),
        ("actions.check_disk", "check_disk",
         {"disk_count", "disk_total_bytes", "disk_used_bytes", "disk_free_bytes",
          "disk_percent", "disks"}),
        ("actions.check_network_speed", "check_network_speed",
         {"network_down_mb_s", "network_up_mb_s"}),
        ("actions.check_temperature", "check_temperature",
         {"temperature_celsius"}),
        ("actions.check_gpu", "check_gpu",
         {"gpu_percent", "gpu_memory_percent", "gpu_memory_used_bytes",
          "gpu_memory_total_bytes"}),
        ("actions.check_cpu", "check_cpu",
         {"cpu_percent", "cpu_cores_percent", "cpu_threshold_percent",
          "cpu_sustain_seconds", "cpu_sustained", "cpu_sustained_seconds",
          "trend_60"}),
        ("actions.check_ram", "check_ram",
         {"memory_percent", "memory_used_bytes", "memory_total_bytes"}),
        ("actions.check_system", "check_system", None),
    ],
)
def test_distinct_voice_actions_expose_one_tool_and_only_category_metrics(
    monkeypatch, module_name, tool_name, keys,
):
    module = importlib.import_module(module_name)

    snapshot = {"cpu_percent": 1} if keys is None else {key: key for key in keys}
    pulse = SimpleNamespace(snapshot=lambda: snapshot)
    hub = SimpleNamespace(get_module=lambda name: pulse if name == "pulse" else None)
    monkeypatch.setattr(action_helpers, "get_symbiosis_hub", lambda **_: hub)
    assert module.TOOL["name"] == tool_name
    result = json.loads(module.TOOL["handler"]({}))
    if keys is not None:
        assert set(result) == keys


def test_all_requested_actions_register_as_individual_tools():
    actions_dir = Path(__file__).resolve().parents[1] / "actions"
    registry = discover_actions(actions_dir, logger=lambda _message: None)
    assert {
        "check_system", "check_cpu", "check_ram", "check_disk",
        "check_battery", "check_gpu", "check_network_speed", "check_temperature",
    } <= registry.names()


@pytest.mark.parametrize("state", ["disabled", "inactive", "unselected"])
def test_actions_never_start_hub_when_disabled_or_pulse_unselected(monkeypatch, state):
    import core.symbiosis_hub as hub_module

    calls = []

    class FakePulse:
        def start(self):
            calls.append("start")

        def stop(self, timeout=0):
            return True

        def snapshot(self):
            return {"cpu_percent": 42}

    hub_module.stop_symbiosis_hub()
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "0" if state == "disabled" else "1")
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", "")
    monkeypatch.setattr(hub_module.SymbiosisHub, "_create", staticmethod(lambda _: FakePulse()))
    if state == "unselected":
        hub_module.get_symbiosis_hub()
    registry = discover_actions(Path(__file__).resolve().parents[1] / "actions",
                                logger=lambda _: None)
    try:
        for name in (
            "system_pulse", "check_system", "check_cpu", "check_ram", "check_disk",
            "check_battery", "check_gpu", "check_network_speed", "check_temperature",
        ):
            result = json.loads(registry.run(name, {}))
            assert "error" in result
            assert ("pulse" if state == "unselected" else "SymbiosisHub") in result["error"]
        assert calls == []
        if state != "unselected":
            assert hub_module._hub is None
    finally:
        hub_module.stop_symbiosis_hub()


def test_actions_use_existing_hub_collector_via_discovery(monkeypatch):
    import core.symbiosis_hub as hub_module

    calls = []

    class FakePulse:
        def start(self):
            calls.append("start")

        def stop(self, timeout=0):
            return True

        def snapshot(self):
            calls.append("snapshot")
            result = SystemPulse().snapshot()
            result["cpu_percent"] = 42
            return result

    hub_module.stop_symbiosis_hub()
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "1")
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", "pulse")
    pulse = FakePulse()
    monkeypatch.setattr(hub_module.SymbiosisHub, "_create", staticmethod(lambda _: pulse))
    try:
        hub = hub_module.get_symbiosis_hub()
        assert hub.get_module("pulse") is pulse
        registry = discover_actions(Path(__file__).resolve().parents[1] / "actions",
                                    logger=lambda _: None)
        for name in (
            "system_pulse", "check_system", "check_cpu", "check_ram", "check_disk",
            "check_battery", "check_gpu", "check_network_speed", "check_temperature",
        ):
            result = json.loads(registry.run(name, {}))
            assert "error" not in result, name
        assert calls == ["start"] + ["snapshot"] * 9
        assert pulse_module.get_system_pulse() is pulse
    finally:
        hub_module.stop_symbiosis_hub()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interval": 0},
        {"interval": float("nan")},
        {"cpu_threshold": 101},
        {"cpu_sustain_seconds": -1},
    ],
)
def test_rejects_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        SystemPulse(**kwargs)

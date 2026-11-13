import threading
import time

import pytest

from core.symbiosis_hub import SymbiosisHub, get_symbiosis_hub, stop_symbiosis_hub


class FakeModule:
    def __init__(self, value):
        self.value = value
        self.running = False

    def start(self):
        self.running = True

    def stop(self, timeout=3):
        self.running = False
        return True

    def snapshot(self):
        return self.value


def test_hub_lifecycle_and_context_privacy():
    pulse = FakeModule({"cpu_percent": 99, "memory_percent": 50, "private": "do-not-export",
                        "sampled_at_monotonic": time.monotonic()})
    process = FakeModule({"processes": [{"name": "code.exe", "cpu_percent": 1, "stale": False, "path": "C:\\private"}]})
    hub = SymbiosisHub(modules={"pulse", "process"}, factories={"pulse": lambda: pulse, "process": lambda: process})
    hub.start()
    hub.start()
    assert pulse.running and process.running
    summary = hub.get_context_summary()
    assert summary["pulse"]["cpu_percent"] == 99
    assert summary["pulse"]["ram_percent"] == 50
    assert "private" not in repr(summary)
    assert "C:\\\\private" not in repr(hub.get_hud_state())
    assert hub.shutdown()
    assert not pulse.running and not process.running


def test_environment_disables_hub(monkeypatch):
    stop_symbiosis_hub()
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "0")
    assert get_symbiosis_hub() is None


def test_unknown_module_and_unavailable_sources():
    with pytest.raises(ValueError):
        SymbiosisHub(modules={"mystery"})
    def fail():
        raise OSError("unavailable")
    hub = SymbiosisHub(modules={"pulse"}, factories={"pulse": fail})
    hub.start()
    assert hub.get_full_symbiosis_state() == {}
    assert hub.shutdown()


def test_selective_singleton(monkeypatch):
    import core.symbiosis_hub as module
    fake = FakeModule({"cpu_percent": 7})
    stop_symbiosis_hub()
    monkeypatch.delenv("JARVIS_SYMBIOSIS", raising=False)
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", "pulse")
    monkeypatch.setattr(SymbiosisHub, "_create", staticmethod(lambda name: fake))
    try:
        assert module.get_symbiosis_hub() is module.get_symbiosis_hub()
        assert fake.running
    finally:
        stop_symbiosis_hub()
    assert not fake.running


def test_module_failure_does_not_leak_data():
    class Broken(FakeModule):
        def snapshot(self):
            raise RuntimeError("secret details")
        def stop(self, timeout=3):
            return False
    hub = SymbiosisHub(modules={"pulse"}, factories={"pulse": lambda: Broken({})})
    hub.start()
    assert hub.get_full_symbiosis_state()["pulse"] == {"error": "dato non disponibile"}
    assert not hub.shutdown()


def test_hub_clipboard_and_network_are_metadata_only():
    class Clip(FakeModule):
        def metadata(self, limit):
            return [{"type": "url", "length": 3}]
    class Network(FakeModule):
        def snapshot(self):
            return {"connected": True, "wifi_signal_percent": 20, "ssid": "private",
                    "sampled_at_monotonic": time.monotonic()}
    clip = Clip({})
    net = Network({})
    hub = SymbiosisHub(modules={"clipboard", "network"},
                       factories={"clipboard": lambda: clip, "network": lambda: net})
    hub.start()
    assert hub.clipboard is clip
    result = hub.get_hud_state()
    assert result["clipboard"] == [{"type": "url", "length": 3}]
    assert result["network"]["connected"]
    assert "private" not in repr(result)
    assert hub.shutdown()


def test_context_projects_pulse_and_process_without_private_data(monkeypatch):
    import core.symbiosis_hub as facade
    from core.context_awareness import ContextEngine
    pulse = FakeModule({"cpu_percent": 95, "memory_percent": 88,
                        "battery_percent": 10, "battery_plugged": False,
                        "temperature_celsius": 90,
                        "sampled_at_monotonic": time.monotonic(),
                        "disks": [{"drive": "C:\\", "free_bytes": 4_000_000_000}]})
    process = FakeModule({"processes": [{"name": "chrome.exe", "cpu_percent": 90,
                                          "memory_percent": 12, "status": "running", "stale": False,
                                          "path": "C:\\private"}]})
    hub = SymbiosisHub(modules={"pulse", "process"},
                       factories={"pulse": lambda: pulse, "process": lambda: process})
    hub.start()
    monkeypatch.setattr(facade, "get_symbiosis_hub", lambda **_: hub)
    context = ContextEngine().get_context()
    summary = context["symbiosis"]
    assert summary["pulse"]["cpu_percent"] == 95
    assert summary["pulse"]["disk_free_gb"] == 4
    assert summary["pulse"]["temperature_c"] == 90
    assert summary["process"]["hog"]["name"] == "chrome.exe"
    assert "private" not in repr(summary)
    assert hub.shutdown()


def test_hud_exposes_symbiosis_without_html_interpretation():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "core" / "jarvis_hud.html").read_text(encoding="utf-8")
    assert 'id="symbiosis-status"' in html
    assert '$("symbiosis-status").textContent=m.symbiosis?' in html


def test_hog_summary_excludes_protected_processes():
    process = FakeModule({"hogs": [
        {"name": "csrss.exe", "cpu_percent": 99, "protected": True, "stale": False},
        {"name": "chrome.exe", "cpu_percent": 90, "protected": False, "stale": False},
    ]})
    hub = SymbiosisHub(modules={"process"}, factories={"process": lambda: process})
    hub.start()
    assert hub.get_context_summary()["process"]["hog"]["name"] == "chrome.exe"
    assert hub.shutdown()


def test_stale_samples_are_not_projected_into_context_or_hud():
    pulse = FakeModule({"cpu_percent": 95, "sampled_at_monotonic": time.monotonic() - 11})
    process = FakeModule({"processes": [
        {"name": "chrome.exe", "cpu_percent": 95, "stale": True},
    ]})
    hub = SymbiosisHub(modules={"pulse", "process"},
                       factories={"pulse": lambda: pulse, "process": lambda: process})
    hub.start()
    assert hub.get_context_summary()["pulse"]["cpu_percent"] is None
    assert hub.get_context_summary()["process"]["hog"] is None
    assert hub.get_hud_state()["top_processes"] == []
    assert hub.shutdown()


def test_context_summary_never_reads_clipboard():
    class Clip(FakeModule):
        def metadata(self, limit):
            raise AssertionError("Context must not wait for clipboard persistence")

    hub = SymbiosisHub(modules={"clipboard"}, factories={"clipboard": lambda: Clip({})})
    hub.start()
    assert hub.get_context_summary()["pulse"]["cpu_percent"] is None
    assert hub.shutdown()


def test_check_context_remains_fast_during_blocked_network_poll(monkeypatch):
    import actions.check_context as action
    import core.symbiosis_hub as facade
    from core.context_awareness import ContextEngine
    from core.network_security import NetworkSecurityMonitor, NetworkSnapshot

    entered, release = threading.Event(), threading.Event()

    def blocked_scan():
        entered.set()
        release.wait(2)
        return NetworkSnapshot(status="available")

    monitor = NetworkSecurityMonitor(interval_seconds=0.01, snapshot_source=blocked_scan)
    hub = SymbiosisHub(modules={"network"}, factories={"network": lambda: monitor})
    hub.start()
    monkeypatch.setattr(facade, "get_symbiosis_hub", lambda **_: hub)
    monkeypatch.setattr(action, "current_context", ContextEngine().get_context)
    try:
        assert entered.wait(1)
        start = time.monotonic()
        result = action.check_context({})
        assert time.monotonic() - start < 0.1
        assert "Calendario:" in result
    finally:
        release.set()
        assert hub.shutdown()

"""Lifecycle and privacy boundary for hardware-awareness modules."""
from __future__ import annotations

import logging
import math
import os
import re
import threading
import time

_LOG = logging.getLogger(__name__)
_NAMES = frozenset({"pulse", "process", "clipboard", "network", "monitor"})
_hub = None
_hub_lock = threading.Lock()


class SymbiosisHub:
    def __init__(self, *, modules: set[str] | None = None, factories: dict | None = None):
        requested = set(_NAMES) if modules is None else set(modules)
        unknown = requested - _NAMES
        if unknown:
            raise ValueError(f"Moduli simbiosi non riconosciuti: {', '.join(sorted(unknown))}")
        self._selected = requested
        self._factories = factories or {}
        self._modules = {}
        self._lock = threading.RLock()
        self._started = False

    @property
    def clipboard(self):
        return self.get_module("clipboard")

    def get_module(self, name: str):
        with self._lock:
            return self._modules.get(name)

    @staticmethod
    def _create(name):
        if name == "pulse":
            from core.system_pulse import SystemPulse
            return SystemPulse(interval=5.0, cpu_sustain_seconds=120)
        if name == "process":
            from core.process_master import ProcessMaster
            return ProcessMaster()
        if name == "clipboard":
            from core.clipboard_intelligence import ClipboardIntelligence
            return ClipboardIntelligence()
        if name == "network":
            from core.network_security import NetworkSecurityMonitor
            return NetworkSecurityMonitor(interval_seconds=30.0)
        if name == "monitor":
            from core.multi_monitor import MultiMonitorManager
            return MultiMonitorManager(poll_interval=3.0)
        raise ValueError(f"Modulo simbiosi non valido: {name}")

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True
            for name in sorted(self._selected):
                try:
                    module = self._factories[name]() if name in self._factories else self._create(name)
                    module.start()
                    self._modules[name] = module
                except Exception:
                    _LOG.exception("[SYMBIOSIS][%s] Avvio non riuscito", name.upper())
            _LOG.info("[SYMBIOSIS] Hub avviato con %d moduli attivi", len(self._modules),
                      extra={"component": "symbiosis.hub"})

    def get_full_symbiosis_state(self, *, include_clipboard: bool = True) -> dict:
        with self._lock:
            modules = dict(self._modules)
        result = {}
        for name, module in modules.items():
            if name == "clipboard" and not include_clipboard:
                continue
            try:
                if name == "clipboard":
                    result[name] = module.metadata(10)
                else:
                    result[name] = module.snapshot()
            except Exception:
                _LOG.exception("[SYMBIOSIS][%s] Lettura stato non riuscita", name.upper())
                result[name] = {"error": "dato non disponibile"}
        return result

    def get_context_summary(self) -> dict:
        raw = self.get_full_symbiosis_state(include_clipboard=False)
        pulse = raw.get("pulse") or {}
        network = raw.get("network") or {}
        process = raw.get("process") or {}
        monitor = raw.get("monitor") or {}
        process_items = process.get("hogs", [])
        all_processes = process.get("processes") or []
        process_module = self.get_module("process")
        process_max_age = 2 * getattr(process_module, "refresh_interval", 10)
        process_captured = process.get("captured_at")
        process_fresh = (
            isinstance(process_captured, (int, float)) and not isinstance(process_captured, bool)
            and math.isfinite(process_captured) and 0 <= time.time() - process_captured <= process_max_age
        )
        if not process_items and isinstance(all_processes, list):
            process_items = sorted((item for item in all_processes if isinstance(item, dict)
                                    and item.get("stale") is False
                                    and isinstance(item.get("cpu_percent"), (int, float))),
                                   key=lambda item: item["cpu_percent"], reverse=True)
        hog = next((item for item in process_items if isinstance(item, dict)
                    and item.get("stale") is False
                    and item.get("protected") is not True), None) if isinstance(process_items, list) else None
        safe_hog = None
        if isinstance(hog, dict) and hog.get("protected") is not True:
            name, cpu = hog.get("name"), hog.get("cpu_percent")
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.+\-]{1,80}", name):
                reference = hog.get("reference")
                safe_hog = {"name": name, "cpu_percent": cpu,
                            "identity": reference if isinstance(reference, str) else name,
                            "observed_at": hog.get("observed_at"),
                            "fresh_for_seconds": process_max_age,
                            "cpu_high_for_seconds": hog.get("cpu_high_for_seconds")}
        pulse_module = self.get_module("pulse")
        sampled_at = pulse.get("sampled_at_monotonic")
        max_age = 2 * getattr(pulse_module, "interval", 5)
        pulse_fresh = (
            isinstance(sampled_at, (int, float)) and not isinstance(sampled_at, bool)
            and math.isfinite(sampled_at) and 0 <= time.monotonic() - sampled_at <= max_age
        )
        if not pulse_fresh:
            pulse = {}
        network_module = self.get_module("network")
        network_max_age = 2 * getattr(network_module, "interval_seconds", 30)
        network_sampled = network.get("sampled_at_monotonic")
        network_fresh = (
            isinstance(network_sampled, (int, float)) and not isinstance(network_sampled, bool)
            and math.isfinite(network_sampled) and 0 <= time.monotonic() - network_sampled <= network_max_age
        )
        if not network_fresh:
            network = {}
        disks = pulse.get("disks") or []
        system_disk = next((disk for disk in disks if isinstance(disk, dict)
                            and str(disk.get("drive", "")).casefold().rstrip("\\/") == "c:"), None)
        free_bytes = system_disk.get("free_bytes") if system_disk else None
        disk_free_gb = free_bytes / 1_000_000_000 if isinstance(free_bytes, (int, float)) else None
        wifi = network.get("wifi") or {}
        interfaces = network.get("interfaces") or {}
        return {
            "pulse": {
                "cpu_percent": pulse.get("cpu_percent"),
                "ram_percent": pulse.get("ram_percent", pulse.get("memory_percent")),
                "battery_percent": pulse.get("battery_percent"),
                "battery_plugged": pulse.get("battery_plugged"),
                "disk_free_gb": disk_free_gb,
                "temperature_c": pulse.get("temperature_celsius"),
                "gpu_percent": pulse.get("gpu_percent"),
                "sampled_at_monotonic": pulse.get("sampled_at_monotonic"),
                "fresh_for_seconds": max_age,
                "cpu_sustained_seconds": pulse.get("cpu_sustained_seconds"),
            },
            "process": {"hog": safe_hog,
                        "zombies": process_fresh and (bool(process.get("zombies")) or any(
                            isinstance(item, dict) and item.get("stale") is False
                            and item.get("status") == "zombie" for item in all_processes))},
            "network": {"connected": network.get("connected", interfaces.get("connected")),
                        "wifi_signal_percent": network.get("wifi_signal_percent", wifi.get("signal_percent")),
                        "sampled_at_monotonic": network.get("sampled_at_monotonic"),
                        "fresh_for_seconds": network_max_age,
                        "wifi_weak_seconds": network.get("wifi_weak_seconds")},
            "monitor": {"change_counter": monitor.get("change_counter"),
                        "active": (monitor.get("active_monitor") or {}).get("index")},
        }

    def get_hud_state(self) -> dict:
        summary = self.get_context_summary()
        with self._lock:
            clipboard = self._modules.get("clipboard")
            process = self._modules.get("process")
        if clipboard is not None:
            summary["clipboard"] = clipboard.metadata(10)
        if process is not None:
            snapshot = process.snapshot()
            items = snapshot.get("processes", []) if isinstance(snapshot, dict) else []
            items = sorted((item for item in items if isinstance(item, dict)
                            and item.get("stale") is False),
                           key=lambda item: item.get("cpu_percent") or 0, reverse=True)
            summary["top_processes"] = [
                {"name": item["name"], "cpu_percent": item.get("cpu_percent"), "ram_percent": item.get("memory_percent")}
                for item in items[:5] if isinstance(item, dict) and isinstance(item.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9_.+\-]{1,80}", item["name"])
            ]
        return summary

    def get_local_network_details(self, category: str) -> dict:
        network = self.get_module("network")
        if network is None:
            raise RuntimeError("Monitoraggio rete non disponibile.")
        from core import network_security
        readers = {
            "wifi": network_security.local_wifi_details,
            "interfaces": network_security.local_interface_details,
            "ports": network_security.local_listening_ports,
            "neighbors": network_security.local_network_neighbors,
            "public_ip": network.local_public_ip,
        }
        if category not in readers:
            raise ValueError("Categoria rete non valida.")
        return readers[category]()

    def shutdown(self) -> bool:
        with self._lock:
            modules = list(self._modules.items())
            self._modules = {}
            self._started = False
        deadline = time.monotonic() + 3.0
        results = {}

        def stop_module(name, module):
            try:
                remaining = max(0.0, deadline - time.monotonic())
                results[name] = module.stop(timeout=remaining) is not False
                if not results[name]:
                    _LOG.error("[SYMBIOSIS][%s] Arresto incompleto", name.upper())
            except Exception:
                results[name] = False
                _LOG.exception("[SYMBIOSIS][%s] Arresto non riuscito", name.upper())

        workers = [threading.Thread(target=stop_module, args=(name, module), daemon=True)
                   for name, module in modules]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))
        if any(worker.is_alive() for worker in workers):
            _LOG.error("[SYMBIOSIS] Arresto non completato entro tre secondi")
            return False
        if os.environ.get("JARVIS_LOG_LEGACY") != "1" and os.environ.get("JARVIS_LOG_DIAGNOSTIC", "1") == "1":
            _LOG.info("[SYMBIOSIS] Hub arrestato", extra={"component": "symbiosis.hub"})
        return all(results.values())


def get_symbiosis_hub(*, start: bool = True) -> SymbiosisHub | None:
    global _hub
    if os.environ.get("JARVIS_SYMBIOSIS", "1") == "0":
        return None
    with _hub_lock:
        if _hub is None and start:
            names = os.environ.get("JARVIS_SYMBIOSIS_MODULES")
            selected = {name.strip().casefold() for name in names.split(",") if name.strip()} if names is not None else None
            _hub = SymbiosisHub(modules=selected)
            _hub.start()
        return _hub


def stop_symbiosis_hub() -> bool:
    global _hub
    with _hub_lock:
        hub, _hub = _hub, None
    return hub.shutdown() if hub is not None else True

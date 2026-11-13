"""Thread-safe, privacy-conscious snapshots of local system health metrics."""
from __future__ import annotations

import logging
import math
import os
import platform
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

import psutil

_LOG = logging.getLogger(__name__)
_TREND_SAMPLES = 60
_TREND_METRICS = (
    "cpu_percent",
    "memory_percent",
    "disk_percent",
    "temperature_celsius",
    "network_received_bytes_per_second",
    "network_sent_bytes_per_second",
    "gpu_percent",
)


class SystemPulse:
    """Periodically collect aggregate system metrics without exposing identifiers."""

    def __init__(
        self,
        *,
        interval: float = 5.0,
        cpu_threshold: float = 90.0,
        cpu_sustain_seconds: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("System pulse interval must be positive.")
        if not math.isfinite(cpu_threshold) or not 0 <= cpu_threshold <= 100:
            raise ValueError("CPU threshold must be between 0 and 100.")
        if not math.isfinite(cpu_sustain_seconds) or cpu_sustain_seconds < 0:
            raise ValueError("CPU sustain duration cannot be negative.")
        self.interval = interval
        self.cpu_threshold = cpu_threshold
        self.cpu_sustain_seconds = cpu_sustain_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._sample_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cpu_high_since: float | None = None
        self._cpu_last_high_at: float | None = None
        self._network_previous: tuple[float, int, int] | None = None
        self._history: deque[tuple[float, dict[str, float | None]]] = deque(
            maxlen=_TREND_SAMPLES
        )
        self._metrics: dict[str, Any] = self._empty_metrics()

    @staticmethod
    def _empty_metrics() -> dict[str, Any]:
        return {
            "cpu_percent": None,
            "sampled_at_monotonic": None,
            "timestamp": None,
            "cpu_cores_percent": None,
            "memory_percent": None,
            "memory_used_bytes": None,
            "memory_total_bytes": None,
            "process_count": None,
            "uptime_seconds": None,
            "disks": None,
            "disk_count": None,
            "disk_total_bytes": None,
            "disk_used_bytes": None,
            "disk_free_bytes": None,
            "disk_percent": None,
            "battery_percent": None,
            "battery_plugged": None,
            "battery_seconds_left": None,
            "temperature_celsius": None,
            "network_received_bytes_per_second": None,
            "network_sent_bytes_per_second": None,
            "network_download_mb_s": None,
            "network_upload_mb_s": None,
            "network_down_mb_s": None,
            "network_up_mb_s": None,
            "gpu_percent": None,
            "gpu_memory_percent": None,
            "gpu_memory_used_bytes": None,
            "gpu_memory_total_bytes": None,
            "cpu_threshold_percent": None,
            "cpu_sustain_seconds": None,
            "cpu_sustained": False,
            "cpu_sustained_seconds": 0.0,
            "trend_60": SystemPulse._empty_trend(),
        }

    @staticmethod
    def _empty_trend() -> dict[str, Any]:
        return {
            "sample_count": 0,
            "window_seconds": 0.0,
            "metrics": {
                name: {
                    "min": None, "average": None, "max": None,
                    "change": None, "direction": None,
                }
                for name in _TREND_METRICS
            },
        }

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the daemon collector; repeated calls while running are harmless."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            try:
                psutil.cpu_percent(interval=None)
                psutil.cpu_percent(interval=None, percpu=True)
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Inizializzazione CPU non riuscita")
            self._sample(include_cpu=True)
            self._thread = threading.Thread(
                target=self._run,
                name="jarvis-system-pulse",
                daemon=True,
            )
            self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval):
            try:
                self.sample_once()
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Campionamento non riuscito")
                with self._lock:
                    self._cpu_high_since = None
                    self._cpu_last_high_at = None
                    self._network_previous = None
                    self._history.clear()
                    self._metrics = self._empty_metrics()

    def stop(self, timeout: float = 2.0) -> bool:
        """Request shutdown and return whether the collector stopped in time."""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        stopped = thread is None or not thread.is_alive()
        if stopped:
            with self._lock:
                if self._thread is thread:
                    self._thread = None
                    self._cpu_high_since = None
                    self._cpu_last_high_at = None
        return stopped

    def snapshot(self) -> dict[str, Any]:
        """Return a detached copy of the latest privacy-filtered metrics."""
        with self._lock:
            result = dict(self._metrics)
            disks = self._metrics["disks"]
            result["disks"] = [dict(disk) for disk in disks] if disks is not None else None
            cores = self._metrics["cpu_cores_percent"]
            result["cpu_cores_percent"] = list(cores) if cores is not None else None
            trend = self._metrics["trend_60"]
            result["trend_60"] = {
                "sample_count": trend["sample_count"],
                "window_seconds": trend["window_seconds"],
                "metrics": {
                    name: dict(stats) for name, stats in trend["metrics"].items()
                },
            }
            return result

    def get_trend(self, metric: str) -> str:
        """Return a metric's direction; fail explicitly if no measurement exists."""
        trend = self.snapshot()["trend_60"]
        if metric not in trend["metrics"]:
            raise ValueError(f"Unknown trend metric: {metric}")
        direction = trend["metrics"][metric]["direction"]
        if direction is None:
            raise ValueError(f"Trend unavailable for metric: {metric}")
        return direction

    def get_pulse(self) -> dict[str, Any]:
        """Return the latest metrics snapshot."""
        return self.snapshot()

    def sample_once(self) -> dict[str, Any]:
        """Synchronously refresh a snapshot, useful for explicit on-demand reads."""
        return self._sample(include_cpu=True)

    @staticmethod
    def _valid_number(value: Any, *, minimum: float = 0.0) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        number = float(value)
        if not math.isfinite(number) or number < minimum:
            return None
        return number

    @classmethod
    def _valid_percent(cls, value: Any) -> float | None:
        number = cls._valid_number(value)
        return number if number is not None and number <= 100 else None

    def _read_disks(self) -> list[dict[str, str | int | float | None]] | None:
        disks: list[dict[str, str | int | float | None]] = []
        seen: set[tuple[str, str]] = set()
        try:
            partitions = psutil.disk_partitions(all=False)
            for partition in partitions:
                identity = (partition.device, partition.mountpoint)
                if identity in seen:
                    continue
                seen.add(identity)
                mountpoint = str(partition.mountpoint)
                if (platform.system() == "Windows" and len(mountpoint) >= 2
                        and mountpoint[1] == ":" and mountpoint[0].isalpha()):
                    label = mountpoint[:2].upper()
                else:
                    label = f"Drive {len(disks) + 1}"
                disk: dict[str, str | int | float | None] = {
                    "drive": label, "total_bytes": None, "used_bytes": None,
                    "free_bytes": None, "percent": None,
                }
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    for field, attr in (("total_bytes", "total"), ("used_bytes", "used"),
                                        ("free_bytes", "free")):
                        value = self._valid_number(getattr(usage, attr, None))
                        disk[field] = int(value) if value is not None else None
                    disk["percent"] = self._valid_percent(getattr(usage, "percent", None))
                    if disk["percent"] is None:
                        _LOG.warning("[SYMBIOSIS][PULSE] Percentuale disco non valida")
                except Exception:
                    _LOG.warning("[SYMBIOSIS][PULSE] Lettura disco non riuscita")
                disks.append(disk)
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Enumerazione dischi non riuscita")
            return None
        return disks

    @classmethod
    def _read_temperature(cls) -> float | None:
        temperatures = None
        sensor_reader = getattr(psutil, "sensors_temperatures", None)
        if sensor_reader is not None:
            try:
                temperatures = sensor_reader()
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Lettura temperature non riuscita")
        if temperatures:
            candidates = []
            preferred = {"coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"}
            for name, entries in temperatures.items():
                if name.casefold() not in preferred:
                    continue
                for entry in entries:
                    value = cls._valid_number(getattr(entry, "current", None), minimum=-273.15)
                    if value is not None:
                        candidates.append(value)
            if not candidates:
                for entries in temperatures.values():
                    for entry in entries:
                        value = cls._valid_number(
                            getattr(entry, "current", None), minimum=-273.15
                        )
                        if value is not None:
                            candidates.append(value)
            if candidates:
                return max(candidates)

        if os.name == "nt":
            try:
                import wmi
            except ImportError:
                return None
            try:
                zones = wmi.WMI(namespace="root/wmi").MSAcpi_ThermalZoneTemperature()
                values = [
                    cls._valid_number((zone.CurrentTemperature / 10.0) - 273.15,
                                      minimum=-273.15)
                    for zone in zones
                ]
                valid = [value for value in values if value is not None]
                if valid:
                    return max(valid)
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Lettura temperature WMI non riuscita")
        return None

    @classmethod
    def _read_gpu(cls) -> dict[str, float | None]:
        result = {
            "gpu_percent": None,
            "gpu_memory_percent": None,
            "gpu_memory_used_bytes": None,
            "gpu_memory_total_bytes": None,
        }
        try:
            import pynvml

            initialized = False
            try:
                pynvml.nvmlInit()
                initialized = True
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
                result["gpu_percent"] = cls._valid_percent(utilization.gpu)
                used = cls._valid_number(memory.used)
                total = cls._valid_number(memory.total)
                result["gpu_memory_used_bytes"] = int(used) if used is not None else None
                result["gpu_memory_total_bytes"] = int(total) if total is not None else None
                if used is not None and total:
                    result["gpu_memory_percent"] = min(used / total * 100.0, 100.0)
            finally:
                if initialized:
                    with suppress(Exception):
                        pynvml.nvmlShutdown()
        except Exception:
            with suppress(Exception):
                import GPUtil

                devices = GPUtil.getGPUs()
                if devices:
                    device = devices[0]
                    result["gpu_percent"] = cls._valid_percent(device.load * 100.0)
                    used = cls._valid_number(device.memoryUsed * 1024**2)
                    total = cls._valid_number(device.memoryTotal * 1024**2)
                    result["gpu_memory_used_bytes"] = int(used) if used is not None else None
                    result["gpu_memory_total_bytes"] = int(total) if total is not None else None
                    if used is not None and total:
                        result["gpu_memory_percent"] = min(used / total * 100.0, 100.0)
        return result

    def _read_network(self, now: float) -> tuple[float | None, float | None]:
        try:
            counters = psutil.net_io_counters(pernic=False)
            received = self._valid_number(counters.bytes_recv)
            sent = self._valid_number(counters.bytes_sent)
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Lettura contatori rete non riuscita")
            self._network_previous = None
            return None, None
        if received is None or sent is None:
            self._network_previous = None
            return None, None
        previous = self._network_previous
        self._network_previous = (now, int(received), int(sent))
        if previous is None:
            return None, None
        elapsed = now - previous[0]
        if elapsed <= 0 or received < previous[1] or sent < previous[2]:
            return None, None
        return (received - previous[1]) / elapsed, (sent - previous[2]) / elapsed

    def _make_trend(self) -> dict[str, Any]:
        if not self._history:
            return self._empty_trend()
        first, last = self._history[0][0], self._history[-1][0]
        stats: dict[str, dict[str, float | None]] = {}
        for name in _TREND_METRICS:
            values = [sample[name] for _, sample in self._history if sample[name] is not None]
            if not values:
                stats[name] = {
                    "min": None, "average": None, "max": None,
                    "change": None, "direction": None,
                }
                continue
            change = values[-1] - values[0] if len(values) > 1 else 0.0
            stable_range = (
                1.0 if name.endswith("_percent") else
                0.5 if name == "temperature_celsius" else
                1024.0
            )
            direction = (
                "rising" if change > stable_range else
                "falling" if change < -stable_range else
                "stable"
            )
            stats[name] = {
                "min": round(min(values), 2),
                "average": round(sum(values) / len(values), 2),
                "max": round(max(values), 2),
                "change": round(change, 2),
                "direction": direction,
            }
        return {
            "sample_count": len(self._history),
            "window_seconds": round(max(0.0, last - first), 1),
            "metrics": stats,
        }

    def _sample(self, *, include_cpu: bool) -> dict[str, Any]:
        with self._sample_lock:
            return self._collect_sample(include_cpu=include_cpu)

    def _collect_sample(self, *, include_cpu: bool) -> dict[str, Any]:
        cpu = None
        cpu_cores = None
        if include_cpu:
            try:
                cpu = self._valid_percent(psutil.cpu_percent(interval=None))
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Lettura CPU non riuscita")
            sampled_at = self._clock()
            timestamp = datetime.now(UTC).isoformat()
            try:
                values = psutil.cpu_percent(interval=None, percpu=True)
                cpu_cores = [self._valid_percent(item) for item in values]
            except Exception:
                _LOG.warning("[SYMBIOSIS][PULSE] Lettura core CPU non riuscita")
        else:
            sampled_at = None
            timestamp = None

        memory_percent = memory_used = memory_total = None
        try:
            memory = psutil.virtual_memory()
            memory_percent = self._valid_percent(memory.percent)
            memory_used = self._valid_number(memory.used)
            memory_total = self._valid_number(memory.total)
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Lettura memoria non riuscita")

        disks = self._read_disks()
        def disk_sum(key: str) -> int | None:
            if not disks or any(not isinstance(disk[key], int) for disk in disks):
                return None
            return sum(disk[key] for disk in disks)

        disk_total = disk_sum("total_bytes")
        disk_used = disk_sum("used_bytes")
        disk_free = disk_sum("free_bytes")
        disk_percent = (
            min(disk_used / disk_total * 100.0, 100.0)
            if disk_total and disk_used is not None else None
        )

        battery_percent = battery_plugged = battery_seconds_left = None
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                battery_percent = self._valid_percent(battery.percent)
                battery_plugged = (
                    battery.power_plugged if isinstance(battery.power_plugged, bool) else None
                )
                seconds_left = self._valid_number(battery.secsleft)
                battery_seconds_left = int(seconds_left) if seconds_left is not None else None
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Lettura batteria non riuscita")

        temperature = None
        try:
            temperature = self._read_temperature()
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Elaborazione temperature non riuscita")
        gpu = self._read_gpu()
        now = self._clock()
        network_received, network_sent = self._read_network(now)

        process_count = uptime = None
        try:
            process_count = self._valid_number(len(psutil.pids()))
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Lettura processi non riuscita")
        try:
            uptime = self._valid_number(time.time() - psutil.boot_time())
        except Exception:
            _LOG.warning("[SYMBIOSIS][PULSE] Lettura uptime non riuscita")

        with self._lock:
            if include_cpu:
                if cpu is not None and cpu > self.cpu_threshold:
                    if (
                        self._cpu_last_high_at is None
                        or sampled_at < self._cpu_last_high_at
                        or sampled_at - self._cpu_last_high_at > 2 * self.interval
                    ):
                        self._cpu_high_since = sampled_at
                    self._cpu_last_high_at = sampled_at
                    sustained_seconds = sampled_at - self._cpu_high_since
                else:
                    self._cpu_high_since = None
                    self._cpu_last_high_at = None
                    sustained_seconds = 0.0
            else:
                self._cpu_high_since = None
                self._cpu_last_high_at = None
                sustained_seconds = 0.0
            values: dict[str, float | None] = {
                "cpu_percent": cpu,
                "cpu_cores_percent": cpu_cores,
                "memory_percent": memory_percent,
                "disk_percent": disk_percent,
                "temperature_celsius": temperature,
                "network_received_bytes_per_second": network_received,
                "network_sent_bytes_per_second": network_sent,
                "gpu_percent": gpu["gpu_percent"],
            }
            if include_cpu:
                self._history.append((now, values))
            self._metrics = {
                "cpu_percent": cpu,
                "sampled_at_monotonic": sampled_at,
                "timestamp": timestamp,
                "cpu_cores_percent": cpu_cores,
                "memory_percent": memory_percent,
                "memory_used_bytes": int(memory_used) if memory_used is not None else None,
                "memory_total_bytes": int(memory_total) if memory_total is not None else None,
                "process_count": int(process_count) if process_count is not None else None,
                "uptime_seconds": uptime,
                "disks": disks,
                "disk_count": len(disks) if disks is not None else None,
                "disk_total_bytes": disk_total,
                "disk_used_bytes": disk_used,
                "disk_free_bytes": disk_free,
                "disk_percent": disk_percent,
                "battery_percent": battery_percent,
                "battery_plugged": battery_plugged,
                "battery_seconds_left": battery_seconds_left,
                "temperature_celsius": temperature,
                "network_received_bytes_per_second": network_received,
                "network_sent_bytes_per_second": network_sent,
                "network_download_mb_s": (
                    network_received / 1_000_000 if network_received is not None else None
                ),
                "network_upload_mb_s": (
                    network_sent / 1_000_000 if network_sent is not None else None
                ),
                "network_down_mb_s": (
                    network_received / 1_000_000 if network_received is not None else None
                ),
                "network_up_mb_s": (
                    network_sent / 1_000_000 if network_sent is not None else None
                ),
                **gpu,
                "cpu_threshold_percent": self.cpu_threshold,
                "cpu_sustain_seconds": self.cpu_sustain_seconds,
                "cpu_sustained": (
                    self._cpu_high_since is not None
                    and sustained_seconds >= self.cpu_sustain_seconds
                ),
                "cpu_sustained_seconds": sustained_seconds,
                "trend_60": self._make_trend(),
            }
            return self.snapshot()


def get_system_pulse() -> SystemPulse:
    """Return the active hub-owned collector without starting the hub."""
    from core.symbiosis_hub import get_symbiosis_hub

    hub = get_symbiosis_hub(start=False)
    if hub is None:
        raise RuntimeError("SymbiosisHub non attivo o disabilitato.")
    pulse = hub.get_module("pulse")
    if pulse is None:
        raise RuntimeError("Modulo pulse non selezionato o non disponibile.")
    return pulse


def get_pulse() -> dict[str, Any]:
    """Return the current snapshot from the active hub-owned collector."""
    return get_system_pulse().get_pulse()


def get_trend(metric: str) -> str:
    """Return the active hub-owned collector's direction for a named metric."""
    return get_system_pulse().get_trend(metric)

"""Safe process inspection and human-confirmed process control."""

from __future__ import annotations

import logging
import math
import ntpath
import os
import secrets
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from core import confirm

_REFERENCE_TTL = 10 * 60
_MAX_REFERENCES = 2000
_MAX_LIST_LIMIT = 200
_STOP_TIMEOUT = 5.0
_DEFAULT_CPU_THRESHOLD = 80.0
_DEFAULT_RAM_THRESHOLD = 80.0
_REFERENCE_LOCK = threading.Lock()
_sampling_state = threading.local()


@dataclass(frozen=True)
class _ProcessReference:
    pid: int
    created: float
    expires: float
    expected_name: str | None = None


@dataclass(frozen=True)
class _LaunchSnapshot:
    executable: str
    arguments: tuple[str, ...]
    cwd: str
    file_identity: tuple[int, int, int, int]


_references: dict[str, _ProcessReference] = {}

_PROTECTED_NAMES = frozenset({
    "system", "idle", "system idle process", "registry", "smss", "csrss",
    "wininit", "services", "lsass", "winlogon", "svchost", "fontdrvhost",
    "dwm", "memory compression", "secure system",
    "systemd", "init", "kthreadd", "launchd", "kernel_task",
})
_PROTECTED_PREFIXES = (
    "kworker", "ksoftirqd", "rcu_", "migration/", "watchdog/",
    "kswapd", "mm_percpu_wq", "cpuhp/",
)


def _process_name(process: psutil.Process) -> str | None:
    try:
        return process.name().strip().lower().removesuffix(".exe")
    except (psutil.Error, OSError, AttributeError):
        return None


def _protected_pids() -> set[int]:
    protected = set(range(100))
    if os.name == "nt":
        protected.update({0, 4})
    try:
        current = psutil.Process(os.getpid())
        protected.add(current.pid)
        protected.update(parent.pid for parent in current.parents())
    except (psutil.Error, OSError, AttributeError):
        protected.add(os.getpid())
    return protected


def _is_protected(process: psutil.Process, protected_pids: set[int] | None = None) -> bool:
    if protected_pids is None:
        protected_pids = _protected_pids()
    if process.pid < 100 or process.pid in protected_pids:
        return True
    name = _process_name(process)
    if not name:
        return True
    return name in _PROTECTED_NAMES or name.startswith(_PROTECTED_PREFIXES)


def _new_reference(pid: int, created: float) -> str:
    now = time.monotonic()
    with _REFERENCE_LOCK:
        expired = [key for key, value in _references.items() if value.expires <= now]
        for key in expired:
            _references.pop(key, None)
        for token, value in _references.items():
            if value.pid == pid and value.created == created:
                _references[token] = _ProcessReference(pid, created, now + _REFERENCE_TTL)
                return token
        if len(_references) >= _MAX_REFERENCES:
            oldest = sorted(_references, key=lambda key: _references[key].expires)
            for key in oldest[: len(_references) - _MAX_REFERENCES + 1]:
                _references.pop(key, None)
        token = secrets.token_urlsafe(18)
        _references[token] = _ProcessReference(pid, created, now + _REFERENCE_TTL)
    return token


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {_MAX_LIST_LIMIT}")


def _read_row(
    process: psutil.Process, protected_pids: set[int] | None = None, *,
    include_status: bool = True,
) -> dict[str, Any]:
    pid = process.pid
    created = process.create_time()
    names = getattr(_sampling_state, "names", None)
    if names is not None:
        cache = _sampling_state.name_cache
        cached = cache.get(pid)
        if cached and cached[0] == created and time.monotonic() - cached[2] < 60:
            name = cached[1]
        else:
            try:
                name = ntpath.basename(process.name().replace("/", "\\")).strip()
                name = "".join(char for char in name if char.isprintable()) or None
            except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
                name = None
            cache[pid] = (created, name, time.monotonic())
        normalized = name.lower().removesuffix(".exe") if name else ""
        protected = (
            pid < 100
            or pid in protected_pids
            or not normalized
            or normalized in _PROTECTED_NAMES
            or normalized.startswith(_PROTECTED_PREFIXES)
        )
    else:
        protected = _is_protected(process, protected_pids)
    reference = _new_reference(pid, created)
    if names is not None:
        names[reference] = name
    return {
        "pid": pid,
        "reference": reference,
        "status": process.status() if include_status else "unknown",
        "cpu_percent": round(process.cpu_percent(interval=None), 1),
        "memory_percent": round(process.memory_percent(), 1),
        "protected": protected,
    }


def _poll_status_is_costly() -> bool:
    return sys.platform == "win32"


def _record_poll_sample(row: dict[str, Any]) -> None:
    state = _sampling_state
    now = time.monotonic()
    previous = state.cpu_samples.get(row["pid"])
    duration = 0.0
    if row["cpu_percent"] > _DEFAULT_CPU_THRESHOLD and previous is not None:
        reference, last_at, last_high, last_duration = previous
        gap = now - last_at
        if reference == row["reference"] and last_high and 0 <= gap <= state.refresh_interval * 2:
            duration = last_duration + gap
    state.cpu_samples[row["pid"]] = (
        row["reference"], now, row["cpu_percent"] > _DEFAULT_CPU_THRESHOLD, duration,
    )
    row["observed_at"] = time.time()
    row["cpu_high_for_seconds"] = duration


def _iter_windows_poll_rows() -> list[dict[str, Any]]:
    """Amortize expensive Windows process queries over successive poll cycles."""
    state = _sampling_state
    pids = sorted(psutil.pids())
    live = set(pids)
    for pid in set(state.row_cache) - live:
        old = state.row_cache.pop(pid)
        state.names.pop(old["reference"], None)
        state.process_cache.pop(pid, None)
        state.name_cache.pop(pid, None)
        state.orphan_suspects.pop(pid, None)
        state.cpu_samples.pop(pid, None)
    if not pids or state.stop_event.is_set():
        return list(state.row_cache.values())

    protected_pids = _protected_pids()
    start = state.cursor % len(pids)
    hot = sorted(
        (pid for pid, row in state.row_cache.items()
         if pid in live and row["cpu_percent"] >= _DEFAULT_CPU_THRESHOLD),
        key=lambda pid: state.row_cache[pid].get("observed_at", 0),
    )[:16]
    candidates = hot + [pids[(start + index) % len(pids)] for index in range(len(pids))]
    budget_start = time.thread_time()
    scanned = 0
    ordinary_scanned = 0
    seen = set()
    for index, pid in enumerate(candidates):
        if scanned >= min(32, len(pids)) or state.stop_event.is_set():
            break
        if pid in seen:
            if index >= len(hot):
                ordinary_scanned += 1
            continue
        if scanned and time.thread_time() - budget_start >= 0.08:
            break
        if index >= len(hot):
            ordinary_scanned += 1
        seen.add(pid)
        scanned += 1
        try:
            process = state.process_cache.get(pid)
            if process is None or not process.is_running():
                process = psutil.Process(pid)
                state.process_cache[pid] = process
            with process.oneshot():
                row = _read_row(process, protected_pids, include_status=False)
                try:
                    ppid = int(process.ppid())
                    missing = (
                        not row["protected"] and ppid > 4 and ppid != pid
                        and ppid not in live and not psutil.pid_exists(ppid)
                    )
                except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
                    missing = False
                identity = (process.create_time(), ppid) if missing else None
                if identity is not None and state.orphan_suspects.get(pid) == identity:
                    row["status"] = "orphan"
                if identity is None:
                    state.orphan_suspects.pop(pid, None)
                else:
                    state.orphan_suspects[pid] = identity
            _record_poll_sample(row)
            old = state.row_cache.get(pid)
            if old and old["reference"] != row["reference"]:
                state.names.pop(old["reference"], None)
            state.row_cache[pid] = row
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            old = state.row_cache.pop(pid, None)
            if old:
                state.names.pop(old["reference"], None)
            state.process_cache.pop(pid, None)
            state.orphan_suspects.pop(pid, None)
            state.cpu_samples.pop(pid, None)
    state.cursor = (start + max(ordinary_scanned, 1)) % len(pids)
    return list(state.row_cache.values())


def _iter_process_rows():
    entries: list[dict[str, Any]] = []
    stop_event = getattr(_sampling_state, "stop_event", None)
    if stop_event is not None and stop_event.is_set():
        return entries
    if stop_event is not None and _poll_status_is_costly():
        return _iter_windows_poll_rows()
    protected_pids = _protected_pids()
    include_status = stop_event is None or not _poll_status_is_costly()
    iterator = iter(psutil.process_iter())
    sampled_pids = set()
    while stop_event is None or not stop_event.is_set():
        try:
            process = next(iterator)
        except StopIteration:
            break
        if stop_event is not None and stop_event.is_set():
            break
        try:
            with process.oneshot():
                row = _read_row(process, protected_pids, include_status=include_status)
            if stop_event is not None:
                _record_poll_sample(row)
                sampled_pids.add(row["pid"])
            entries.append(row)
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            if stop_event is not None:
                _sampling_state.cpu_samples.pop(process.pid, None)
            continue
    if stop_event is not None:
        for pid in set(_sampling_state.cpu_samples) - sampled_pids:
            _sampling_state.cpu_samples.pop(pid, None)
    return sorted(entries, key=lambda item: item["pid"])


def list_top_processes(limit: int = 20, sort_by: str = "cpu") -> list[dict[str, Any]]:
    """Return bounded, non-identifying process metrics sorted by CPU or RAM."""
    _validate_limit(limit)
    if sort_by not in {"cpu", "ram"}:
        raise ValueError("sort_by must be 'cpu' or 'ram'")
    entries = _iter_process_rows()
    key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
    return sorted(entries, key=lambda row: (-row[key], row["pid"]))[:limit]


def list_processes(limit: int = 100, sort_by: str = "cpu") -> list[dict[str, Any]]:
    """Compatibility entry point used by the list_processes action."""
    return list_top_processes(limit=limit, sort_by=sort_by)


def _parent_pid(process: psutil.Process) -> int:
    try:
        return int(process.ppid())
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        return 0


def find_zombies(limit: int = _MAX_LIST_LIMIT) -> list[dict[str, Any]]:
    """Find zombies and likely orphans; PPID 0 or a missing parent is an orphan heuristic."""
    _validate_limit(limit)
    found = []
    for process in psutil.process_iter():
        try:
            with process.oneshot():
                row = _read_row(process)
                ppid = _parent_pid(process)
                status = row["status"]
                issues = []
                if status == psutil.STATUS_ZOMBIE:
                    issues.append("zombie")
                if ppid == 0 or (ppid > 1 and not psutil.pid_exists(ppid)):
                    issues.append("orphan")
                if issues:
                    found.append({**row, "ppid": ppid, "issues": issues})
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            continue
    return sorted(found, key=lambda row: row["pid"])[:limit]


def monitor_hogs(
    cpu_threshold: float = _DEFAULT_CPU_THRESHOLD,
    ram_threshold: float = _DEFAULT_RAM_THRESHOLD,
    limit: int = _MAX_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Return processes meeting either CPU or RAM percentage threshold."""
    _validate_limit(limit)
    for value, name in ((cpu_threshold, "cpu_threshold"), (ram_threshold, "ram_threshold")):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number from 0 to 100")
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError(f"{name} must be a number from 0 to 100")
    entries = _iter_process_rows()
    return [
        {key: value for key, value in row.items() if key != "name"} for row in entries
        if row["cpu_percent"] >= cpu_threshold or row["memory_percent"] >= ram_threshold
    ][:limit]


def _has_temp_marker(value: str) -> bool:
    normalized = value.replace("\\", "/").lower()
    return "temp" in Path(normalized).name or any(
        part in {"temp", "tmp"} for part in normalized.split("/")
    )


def _pe_signature_status(path: str) -> str:
    """Best-effort PE certificate-table presence check; this does not validate trust."""
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as stream:
            if stream.read(2) != b"MZ":
                return "unknown"
            stream.seek(0x3C)
            raw = stream.read(4)
            if len(raw) != 4:
                return "unknown"
            pe_offset = struct.unpack("<I", raw)[0]
            stream.seek(pe_offset)
            if stream.read(4) != b"PE\0\0":
                return "unknown"
            stream.seek(pe_offset + 4 + 16)
            optional_size_raw = stream.read(2)
            if len(optional_size_raw) != 2:
                return "unknown"
            optional_size = struct.unpack("<H", optional_size_raw)[0]
            optional_offset = pe_offset + 24
            stream.seek(optional_offset)
            magic_raw = stream.read(2)
            if len(magic_raw) != 2:
                return "unknown"
            magic = struct.unpack("<H", magic_raw)[0]
            directory_offset = 96 if magic == 0x10B else 112 if magic == 0x20B else None
            if directory_offset is None or optional_size < directory_offset + 40:
                return "unknown"
            stream.seek(optional_offset + directory_offset + 8 * 4)
            certificate = stream.read(8)
            if len(certificate) != 8:
                return "unknown"
            file_offset, certificate_size = struct.unpack("<II", certificate)
            if file_offset == 0 or certificate_size == 0:
                return "unsigned"
            if file_offset + certificate_size > file_size:
                return "unknown"
            return "present_unverified"
    except (OSError, ValueError, struct.error):
        return "unknown"


def find_suspicious(limit: int = _MAX_LIST_LIMIT) -> list[dict[str, Any]]:
    """Flag temporary names/locations and unsigned PE files without exposing paths."""
    _validate_limit(limit)
    found = []
    for process in psutil.process_iter():
        try:
            with process.oneshot():
                row = _read_row(process)
                name = _process_name(process) or ""
                executable = process.exe()
                reasons = []
                if _has_temp_marker(name):
                    reasons.append("temporary_name")
                if _has_temp_marker(executable):
                    reasons.append("temporary_path")
                signature_status = _pe_signature_status(executable)
                if signature_status == "unsigned":
                    reasons.append("unsigned_pe")
                if reasons:
                    found.append({
                        **row,
                        "reasons": reasons,
                        "signature_status": signature_status,
                    })
        except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
            continue
    return sorted(found, key=lambda row: row["pid"])[:limit]


def _get_reference(reference: str) -> _ProcessReference | None:
    if not isinstance(reference, str) or not reference or len(reference) > 128:
        return None
    now = time.monotonic()
    with _REFERENCE_LOCK:
        target = _references.get(reference)
        if target is None:
            return None
        if target.expires <= now:
            _references.pop(reference, None)
            return None
        return target


def _resolve_process(target: _ProcessReference) -> psutil.Process | None:
    try:
        process = psutil.Process(target.pid)
        if (
            not process.is_running() or process.create_time() != target.created
            or (target.expected_name is not None
                and process.name().casefold() != target.expected_name)
        ):
            return None
        return process
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        return None


def _launch_snapshot(process: psutil.Process) -> _LaunchSnapshot | None:
    try:
        executable = os.path.abspath(process.exe())
        arguments = tuple(process.cmdline())
        cwd = os.path.abspath(process.cwd())
        stat = os.stat(executable)
        if (
            not executable
            or not Path(executable).is_file()
            or not arguments
            or not all(isinstance(arg, str) and "\0" not in arg for arg in arguments)
        ):
            return None
        file_identity = (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
        )
        return _LaunchSnapshot(executable, arguments, cwd, file_identity)
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        return None


def _same_launch_snapshot(
    process: psutil.Process, expected: _LaunchSnapshot
) -> bool:
    try:
        stat = os.stat(expected.executable)
        return (
            os.path.abspath(process.exe()) == expected.executable
            and tuple(process.cmdline()) == expected.arguments
            and os.path.abspath(process.cwd()) == expected.cwd
            and (
                stat.st_dev,
                stat.st_ino,
                stat.st_size,
                stat.st_mtime_ns,
            ) == expected.file_identity
        )
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
        return False


def _execute(target: _ProcessReference, operation: str,
             launch: _LaunchSnapshot | None) -> str:
    process = _resolve_process(target)
    if process is None:
        return "The selected process is no longer the same process; nothing was done."
    if _is_protected(process):
        return "The selected process is protected; nothing was done."
    if operation == "restart" and (
        launch is None or not _same_launch_snapshot(process, launch)
    ):
        return "The selected process changed or cannot be restarted safely; nothing was done."

    try:
        process.terminate()
        process.wait(timeout=_STOP_TIMEOUT)
    except psutil.TimeoutExpired:
        return "The selected process did not stop; no forceful kill was attempted."
    except psutil.NoSuchProcess:
        return "The selected process exited before the action; nothing else was done."
    except (psutil.Error, OSError, PermissionError):
        return "The selected process could not be stopped."

    if operation == "terminate":
        return "The selected process was stopped."

    assert launch is not None
    try:
        stat = os.stat(launch.executable)
        file_identity = (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
        )
        if file_identity != launch.file_identity:
            return "The selected executable changed; it was stopped but not restarted."
        psutil.Popen(
            list(launch.arguments),
            executable=launch.executable,
            cwd=launch.cwd,
            shell=False,
            close_fds=True,
        )
    except (psutil.Error, OSError, subprocess.SubprocessError, ValueError):
        return "The selected process stopped, but could not be restarted."
    return "The selected process was restarted with its original arguments."


def _resolve_target(value: str | int) -> tuple[_ProcessReference | None, str]:
    if isinstance(value, bool):
        return None, "The process reference is invalid or expired; list processes again."
    target = _get_reference(value)
    if target is not None:
        return target, ""
    try:
        if isinstance(value, int) or (
            isinstance(value, str) and value.isascii() and value.isdecimal()
        ):
            pid = int(value)
            if pid < 100:
                return None, "The selected process is protected; nothing was done."
            process = psutil.Process(pid)
            return _ProcessReference(pid, process.create_time(), time.monotonic() + _REFERENCE_TTL), ""
        if (
            not isinstance(value, str) or not value or len(value) > 128
            or ntpath.basename(value) != value or "/" in value or "\\" in value
        ):
            return None, "The process reference is invalid or expired; list processes again."
        matches = []
        for process in psutil.process_iter():
            try:
                if process.name().casefold() == value.casefold():
                    matches.append(_ProcessReference(
                        process.pid, process.create_time(), time.monotonic() + _REFERENCE_TTL,
                        value.casefold(),
                    ))
            except psutil.NoSuchProcess:
                continue
            except (psutil.Error, OSError, AttributeError, TypeError, ValueError):
                return None, "Cannot safely resolve the process name; nothing was done."
            if len(matches) > 1:
                return None, "The process name is ambiguous; nothing was done."
        if len(matches) == 1:
            return matches[0], ""
    except (psutil.Error, OSError, AttributeError, TypeError, ValueError, OverflowError):
        pass
    return None, "The process reference is invalid or expired; list processes again."


def request_action(reference: str | int, operation: str) -> str:
    """Queue termination or restart behind the on-screen human confirmation."""
    if operation not in {"terminate", "restart"}:
        return "Unsupported process operation; nothing was done."

    target, error = _resolve_target(reference)
    if target is None:
        return error
    process = _resolve_process(target)
    if process is None:
        return "The selected process is no longer the same process; list processes again."
    if _is_protected(process):
        return "The selected process is protected; nothing was done."

    launch = _launch_snapshot(process) if operation == "restart" else None
    if operation == "restart" and launch is None:
        return "The selected process cannot be restarted safely; nothing was done."

    if confirm.pending_title():
        return "Another confirmation is pending; answer it before requesting process control."

    title = f"Confirm {operation} of process {target.pid}"
    detail = (
        f"This will {operation} the selected process (PID {target.pid}). "
        "Process identity will be checked again before acting."
    )
    result = confirm.request(
        f"process-master-{uuid.uuid4().hex}",
        title,
        detail,
        lambda: _execute(target, operation, launch),
        process_voice=True,
    )
    if "[CONFIRMATION_PENDING]" not in result:
        return "Human confirmation is unavailable; the process was not changed."
    return result


def kill_process(reference: str | int, require_confirmation: bool = True) -> str:
    """Request termination; ``require_confirmation=False`` cannot bypass the HUD."""
    del require_confirmation
    return request_action(reference, "terminate")


def restart_process(reference: str | int, require_confirmation: bool = True) -> str:
    """Request a same-arguments restart; every call still requires HUD approval."""
    del require_confirmation
    return request_action(reference, "restart")


class ProcessMaster:
    """Periodic safe process snapshot service for the hub.

    Names in snapshots are local to the hub and excluded from model actions.
    """

    def __init__(self, refresh_interval: float = 10.0, limit: int = 100):
        if isinstance(refresh_interval, bool) or refresh_interval <= 0:
            raise ValueError("refresh_interval must be positive")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be an integer from 1 to {_MAX_LIST_LIMIT}")
        self.refresh_interval = float(refresh_interval)
        self.limit = limit
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {
            "captured_at": None, "processes": [], "error": None, "zombies": False,
        }
        self._snapshot_ready = threading.Event()

    def start(self) -> None:
        """Start periodic snapshots; repeated calls while running are harmless."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="process-master",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> bool:
        """Stop the refresh worker; return whether it exited before timeout."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a non-negative number")
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        return thread is None or not thread.is_alive()

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow-safe copy of the exact hub snapshot schema."""
        with self._lock:
            now = time.time()
            rows = [
                {**row, "stale": (
                    not isinstance(row.get("observed_at"), (int, float))
                    or not 0 <= now - row["observed_at"] <= self.refresh_interval * 2
                )}
                for row in self._snapshot["processes"]
            ]
            for row in rows:
                if row["stale"]:
                    row["cpu_high_for_seconds"] = 0.0
            return {
                "captured_at": self._snapshot["captured_at"],
                "processes": rows,
                "top_processes": [
                    {**row, "ram_percent": row["memory_percent"]} for row in rows[:5]
                ],
                "hogs": [
                    dict(row) for row in rows
                    if not row["stale"] and (
                        row["cpu_percent"] >= _DEFAULT_CPU_THRESHOLD
                        or row["memory_percent"] >= _DEFAULT_RAM_THRESHOLD
                    )
                ],
                "zombies": self._snapshot["zombies"],
                "error": self._snapshot["error"],
            }

    def _run(self) -> None:
        _sampling_state.stop_event = self._stop_event
        _sampling_state.name_cache = {}
        _sampling_state.names = {}
        _sampling_state.row_cache = {}
        _sampling_state.process_cache = {}
        _sampling_state.orphan_suspects = {}
        _sampling_state.cpu_samples = {}
        _sampling_state.refresh_interval = self.refresh_interval
        _sampling_state.cursor = 0
        try:
            while not self._stop_event.is_set():
                try:
                    rows = list_processes(self.limit)
                    for row in rows:
                        if self._stop_event.is_set():
                            break
                        row.setdefault("observed_at", time.time())
                        row["name"] = _sampling_state.names.get(row["reference"])
                    all_rows = (
                        _sampling_state.row_cache.values()
                        if _poll_status_is_costly() else rows
                    )
                    zombies = any(
                        row["status"] in (psutil.STATUS_ZOMBIE, "orphan")
                        and 0 <= time.time() - row.get("observed_at", 0)
                        <= self.refresh_interval * 2
                        for row in all_rows
                    )
                    error = None
                except Exception as exc:
                    logging.getLogger(__name__).error(
                        "[SYMBIOSIS][PROCESS] Polling failed (%s)", type(exc).__name__
                    )
                    rows = []
                    _sampling_state.cpu_samples.clear()
                    for cached_row in _sampling_state.row_cache.values():
                        cached_row["cpu_high_for_seconds"] = 0.0
                    zombies = None
                    error = type(exc).__name__
                if self._stop_event.is_set():
                    break
                with self._lock:
                    self._snapshot = {
                        "captured_at": time.time() if error is None else None,
                        "processes": rows, "error": error, "zombies": zombies,
                    }
                    self._snapshot_ready.set()
                if self._stop_event.wait(self.refresh_interval):
                    break
        finally:
            del _sampling_state.stop_event
            del _sampling_state.name_cache
            del _sampling_state.names
            del _sampling_state.row_cache
            del _sampling_state.process_cache
            del _sampling_state.orphan_suspects
            del _sampling_state.cpu_samples
            del _sampling_state.refresh_interval
            del _sampling_state.cursor


def get_service() -> ProcessMaster | None:
    """Return the active facade-owned process service without starting the facade."""
    if os.environ.get("JARVIS_SYMBIOSIS", "1") == "0":
        return None
    names = os.environ.get("JARVIS_SYMBIOSIS_MODULES")
    if names is not None and "process" not in {
        name.strip().casefold() for name in names.split(",")
    }:
        return None
    from core.symbiosis_hub import get_symbiosis_hub

    hub = get_symbiosis_hub(start=False)
    if hub is None:
        return None
    return hub.get_module("process")

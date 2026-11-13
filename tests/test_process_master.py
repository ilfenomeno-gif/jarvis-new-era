from __future__ import annotations

import asyncio
import json
import os
import struct
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil
import pytest

from actions import kill_process as kill_action
from actions import process_master as process_action
from actions import restart_process as restart_action
from core import process_master, symbiosis_hub
from core.action_loader import discover_actions


class FakeProcess:
    def __init__(
        self,
        pid=4321,
        created=100.0,
        name="sample.exe",
        executable="",
        arguments=None,
        cwd="",
        protected=False,
        cpu=2.5,
        memory=3.5,
        status="running",
        ppid=9999,
    ):
        self.pid = pid
        self.created = created
        self._name = name
        self._executable = executable
        self._arguments = list(arguments or [])
        self._cwd = cwd
        self.protected = protected
        self._cpu = cpu
        self._memory = memory
        self._status = status
        self._ppid = ppid
        self.stopped = False

    class _Oneshot:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def oneshot(self):
        return self._Oneshot()

    def create_time(self):
        return self.created

    def status(self):
        return self._status

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_percent(self):
        return self._memory

    def ppid(self):
        return self._ppid

    def name(self):
        return self._name

    def is_running(self):
        return not self.stopped

    def parents(self):
        return []

    def exe(self):
        return self._executable

    def cmdline(self):
        return list(self._arguments)

    def cwd(self):
        return self._cwd

    def terminate(self):
        self.stopped = True

    def wait(self, timeout=None):
        return 0


def _use_process(monkeypatch, process):
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [process])
    monkeypatch.setattr(process_master.psutil, "Process", lambda _pid: process)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: {0, 1})
    process_master._references.clear()


def test_listing_returns_opaque_refs_and_only_safe_process_fields(monkeypatch):
    process = FakeProcess(
        name="private-user-app.exe",
        executable=r"C:\Users\Someone\secret.exe",
        arguments=["secret.exe", "--token", "do-not-share"],
        cwd=r"C:\Users\Someone\private",
    )
    _use_process(monkeypatch, process)

    rows = process_master.list_processes()

    assert rows[0]["pid"] == process.pid
    assert rows[0]["reference"]
    assert rows[0]["cpu_percent"] == 2.5
    assert rows[0]["memory_percent"] == 3.5
    assert rows[0]["protected"] is False
    assert set(rows[0]) == {
        "pid", "reference", "status", "cpu_percent", "memory_percent", "protected"
    }
    assert "private-user-app" not in json.dumps(rows)
    assert "secret" not in json.dumps(rows)
    assert "do-not-share" not in json.dumps(rows)


def test_termination_only_runs_after_confirmation_and_rechecks_identity(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    requested = {}
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")

    def request(key, title, detail, run, **_kwargs):
        requested.update(key=key, title=title, detail=detail, run=run)
        return "[CONFIRMATION_PENDING] confirm on HUD"

    monkeypatch.setattr(process_master.confirm, "request", request)
    reference = process_master.list_processes()[0]["reference"]

    result = process_master.kill_process(reference, require_confirmation=False)

    assert "[CONFIRMATION_PENDING]" in result
    assert process.stopped is False
    assert "4321" in requested["title"]
    assert "private" not in requested["detail"].lower()
    requested["run"]()
    assert process.stopped is True


def test_pid_reuse_between_request_and_confirmation_does_not_stop_replacement(
    monkeypatch,
):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    requested = {}
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm,
        "request",
        lambda key, title, detail, run, **_kwargs: (
            requested.update(run=run) or "[CONFIRMATION_PENDING]"
        ),
    )
    reference = process_master.list_processes()[0]["reference"]

    process_master.request_action(reference, "terminate")
    process.created = 200.0
    message = requested["run"]()

    assert "no longer the same process" in message
    assert process.stopped is False


def test_missing_hud_confirmation_never_stops_process(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(process_master.confirm, "_show_cb", None)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    reference = process_master.list_processes()[0]["reference"]

    message = kill_action.kill_process({
        "reference": reference,
        "confirmed": True,
        "require_confirmation": False,
    })

    assert "not changed" in message
    assert process.stopped is False


def test_protected_process_is_never_queued(monkeypatch):
    process = FakeProcess(name="svchost.exe")
    _use_process(monkeypatch, process)
    requested = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm,
        "request",
        lambda *args, **kwargs: requested.append(args),
    )
    reference = process_master.list_processes()[0]["reference"]

    result = process_master.request_action(reference, "terminate")

    assert "protected" in result
    assert requested == []
    assert process.stopped is False


@pytest.mark.parametrize(
    ("pid", "name"),
    [
        (50, "ordinary.exe"),
        (4321, "System"),
        (4321, "csrss.exe"),
        (4321, "winlogon.exe"),
        (4321, "lsass.exe"),
    ],
)
def test_required_system_process_protections(pid, name, monkeypatch):
    process = FakeProcess(pid=pid, name=name)
    _use_process(monkeypatch, process)
    requested = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm,
        "request",
        lambda *args, **kwargs: requested.append(args),
    )
    reference = process_master.list_processes()[0]["reference"]

    message = process_master.kill_process(reference, require_confirmation=False)

    assert "protected" in message
    assert requested == []
    assert process.stopped is False


def test_process_with_unreadable_name_is_treated_as_protected(monkeypatch):
    class UnreadableNameProcess(FakeProcess):
        def name(self):
            raise PermissionError("private process metadata")

    process = UnreadableNameProcess()
    _use_process(monkeypatch, process)
    requested = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm,
        "request",
        lambda *args, **kwargs: requested.append(args),
    )
    reference = process_master.list_processes()[0]["reference"]

    result = process_master.request_action(reference, "terminate")

    assert "protected" in result
    assert requested == []
    assert process.stopped is False


def test_monitor_hogs_applies_cpu_and_ram_thresholds(monkeypatch):
    busy_cpu = FakeProcess(pid=4321, cpu=82, memory=10, ppid=1)
    busy_ram = FakeProcess(pid=4322, cpu=10, memory=91, ppid=1)
    ordinary = FakeProcess(pid=4323, cpu=79, memory=79, ppid=1)
    monkeypatch.setattr(
        process_master.psutil,
        "process_iter",
        lambda: [busy_cpu, busy_ram, ordinary],
    )
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set(range(100)))
    process_master._references.clear()

    monkeypatch.setattr(process_master, "get_service", lambda: None)
    hogs = process_master.monitor_hogs(cpu_threshold=80, ram_threshold=90)

    assert [row["pid"] for row in hogs] == [4321, 4322]


def test_top_processes_sort_by_requested_metric_before_limiting(monkeypatch):
    processes = [
        FakeProcess(pid=4321, cpu=90, memory=10, ppid=1),
        FakeProcess(pid=4322, cpu=20, memory=95, ppid=1),
        FakeProcess(pid=4323, cpu=70, memory=50, ppid=1),
    ]
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: processes)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set(range(100)))
    process_master._references.clear()

    top_cpu = process_master.list_top_processes(limit=1, sort_by="cpu")
    top_ram = process_master.list_top_processes(limit=1, sort_by="ram")

    assert top_cpu[0]["pid"] == 4321
    assert top_ram[0]["pid"] == 4322


def test_find_zombies_reports_zombie_and_orphan_without_personal_details(monkeypatch):
    zombie = FakeProcess(
        pid=4321, status="zombie", ppid=9999,
        name="private-name.exe", executable=r"C:\Users\Private\app.exe",
    )
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [zombie])
    monkeypatch.setattr(process_master.psutil, "pid_exists", lambda _pid: False)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set(range(100)))
    process_master._references.clear()

    rows = process_master.find_zombies()

    assert rows[0]["issues"] == ["zombie", "orphan"]
    assert rows[0]["ppid"] == 9999
    assert "private-name" not in json.dumps(rows)
    assert "Users\\Private" not in json.dumps(rows)


def test_find_suspicious_flags_temp_and_unsigned_without_exposing_name_or_path(
    monkeypatch,
):
    process = FakeProcess(
        name="private-temp-app.exe",
        executable=r"C:\Users\Private\Temp\secret.exe",
    )
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "_pe_signature_status", lambda _path: "unsigned")

    rows = process_master.find_suspicious()

    assert rows[0]["reasons"] == [
        "temporary_name", "temporary_path", "unsigned_pe"
    ]
    assert rows[0]["signature_status"] == "unsigned"
    assert "private-temp-app" not in json.dumps(rows)
    assert "Users\\Private" not in json.dumps(rows)
    assert "secret.exe" not in json.dumps(rows)


def test_restart_reuses_exact_arguments_without_a_shell(monkeypatch, tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_text("test executable")
    process = FakeProcess(
        executable=str(executable),
        arguments=["app.exe", "--profile", "private-profile"],
        cwd=str(tmp_path),
    )
    _use_process(monkeypatch, process)
    requested = {}
    spawns = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")

    def request(key, title, detail, run, **_kwargs):
        requested["run"] = run
        return "[CONFIRMATION_PENDING]"

    monkeypatch.setattr(process_master.confirm, "request", request)
    monkeypatch.setattr(
        process_master.psutil,
        "Popen",
        lambda *args, **kwargs: spawns.append((args, kwargs)),
    )
    reference = process_master.list_processes()[0]["reference"]

    process_master.request_action(reference, "restart")
    result = requested["run"]()

    assert "restarted" in result
    assert process.stopped is True
    assert spawns[0][0][0] == ["app.exe", "--profile", "private-profile"]
    assert spawns[0][1]["executable"] == os.path.abspath(executable)
    assert spawns[0][1]["cwd"] == os.path.abspath(tmp_path)
    assert spawns[0][1]["shell"] is False


def test_restart_refuses_if_arguments_change_while_waiting_for_confirmation(
    monkeypatch, tmp_path
):
    executable = tmp_path / "app.exe"
    executable.write_text("test executable")
    process = FakeProcess(
        executable=str(executable),
        arguments=["app.exe", "--profile", "original"],
        cwd=str(tmp_path),
    )
    _use_process(monkeypatch, process)
    requested = {}
    spawns = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm,
        "request",
        lambda key, title, detail, run, **_kwargs: (
            requested.update(run=run) or "[CONFIRMATION_PENDING]"
        ),
    )
    monkeypatch.setattr(
        process_master.psutil,
        "Popen",
        lambda *args, **kwargs: spawns.append((args, kwargs)),
    )
    reference = process_master.list_processes()[0]["reference"]

    process_master.request_action(reference, "restart")
    process._arguments.append("changed")
    message = requested["run"]()

    assert "changed or cannot be restarted safely" in message
    assert process.stopped is False
    assert spawns == []


def test_distinct_process_actions_each_export_one_registered_tool():
    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions",
        logger=lambda _message: None,
    )

    expected = {
        "list_processes",
        "kill_process",
        "restart_process",
        "find_zombies",
        "top_ram_processes",
        "top_cpu_processes",
        "monitor_hogs",
        "find_suspicious",
    }
    assert expected <= registry.names()
    assert registry.risk_class("kill_process") == "destructive"
    assert registry.risk_class("restart_process") == "destructive"
    assert process_action.TOOL["name"] == "list_processes"
    assert kill_action.TOOL["name"] == "kill_process"
    assert restart_action.TOOL["name"] == "restart_process"
    assert all(
        isinstance(module.TOOL, dict)
        for module in (
            process_action,
            kill_action,
            restart_action,
        )
    )


def test_process_master_service_has_hub_snapshot_schema_and_stops(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "_poll_status_is_costly", lambda: False)
    service = process_master.ProcessMaster(refresh_interval=0.01, limit=5)

    service.start()
    try:
        deadline = time.monotonic() + 1
        snapshot = service.snapshot()
        while snapshot["captured_at"] is None and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = service.snapshot()
    finally:
        assert service.stop()

    assert set(snapshot) == {"captured_at", "processes", "top_processes", "hogs", "zombies", "error"}
    assert isinstance(snapshot["captured_at"], float)
    assert set(snapshot["processes"][0]) == {
        "pid", "reference", "status", "cpu_percent", "memory_percent", "protected", "name",
        "observed_at", "stale", "cpu_high_for_seconds",
    }


@pytest.mark.parametrize("reference", ["", "x" * 129, None, True, r"C:\private\app.exe"])
def test_invalid_references_never_reach_process_lookup(monkeypatch, reference):
    def unexpected_lookup(_pid):
        pytest.fail("invalid references must not resolve a process")

    monkeypatch.setattr(process_master.psutil, "Process", unexpected_lookup)
    assert "invalid or expired" in process_master.kill_process(reference)


def test_expired_reference_and_reused_pid_are_rejected(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    now = [100.0]
    monkeypatch.setattr(process_master.time, "monotonic", lambda: now[0])
    reference = process_master.list_processes()[0]["reference"]
    now[0] += process_master._REFERENCE_TTL + 1

    assert "invalid or expired" in process_master.kill_process(reference)
    assert process.stopped is False
    assert reference not in process_master._references

    reference = process_master.list_processes()[0]["reference"]
    process.created += 0.0001
    assert "no longer the same process" in process_master.kill_process(reference)
    assert process.stopped is False


@pytest.mark.parametrize("accepted,expired", [(False, False), (True, True)])
def test_actual_confirmation_cancellation_and_expiry_do_not_terminate(
    monkeypatch, accepted, expired
):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_args: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    now = [100.0]
    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    reference = process_master.list_processes()[0]["reference"]

    assert "[CONFIRMATION_PENDING]" in process_master.kill_process(reference)
    if expired:
        now[0] += gate.TIMEOUT_SECONDS + 1
    gate.resolve(accepted)

    assert process.stopped is False
    assert gate._pending is None


def test_existing_confirmation_and_failure_to_show_leave_process_untouched(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    gate = process_master.confirm
    reference = process_master.list_processes()[0]["reference"]
    monkeypatch.setattr(gate, "pending_title", lambda: "existing request")
    assert "Another confirmation" in process_master.kill_process(reference)
    assert not process.stopped

    monkeypatch.setattr(gate, "pending_title", lambda: "")
    monkeypatch.setattr(gate, "_pending", None)

    def fail_show(*_args):
        raise RuntimeError("UI unavailable")

    monkeypatch.setattr(gate, "_show_cb", fail_show)
    assert "confirmation is unavailable" in process_master.kill_process(reference)
    assert gate._pending is None
    assert not process.stopped


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (psutil.TimeoutExpired(5), "did not stop"),
        (psutil.NoSuchProcess(4321), "exited before"),
        (psutil.AccessDenied(4321), "could not be stopped"),
    ],
)
def test_stop_failures_never_force_kill_or_restart(monkeypatch, failure, expected):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    reference = process_master.list_processes()[0]["reference"]
    target = process_master._get_reference(reference)
    spawn = []

    def fail_terminate():
        raise failure

    monkeypatch.setattr(process, "terminate", fail_terminate)
    monkeypatch.setattr(process_master.psutil, "Popen", lambda *a, **k: spawn.append(a))
    result = process_master._execute(target, "terminate", None)
    assert expected in result
    assert not process.stopped
    assert not spawn


def test_process_newly_protected_before_confirmation_is_not_stopped(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    callback = {}
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda key, title, detail, run, **_kwargs: callback.update(run=run) or "[CONFIRMATION_PENDING]",
    )
    reference = process_master.list_processes()[0]["reference"]
    process_master.kill_process(reference)
    process._name = "lsass.exe"
    assert "protected" in callback["run"]()
    assert not process.stopped


@pytest.mark.parametrize("arguments", [[], ["app.exe", "invalid\0argument"]])
def test_restart_refuses_unusable_arguments_without_confirmation(
    monkeypatch, tmp_path, arguments
):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"test")
    process = FakeProcess(executable=str(executable), arguments=arguments, cwd=str(tmp_path))
    _use_process(monkeypatch, process)
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda *args, **kwargs: pytest.fail("unsafe restart must not be queued"),
    )
    reference = process_master.list_processes()[0]["reference"]
    assert "cannot be restarted safely" in process_master.restart_process(
        reference, require_confirmation=False
    )
    assert not process.stopped


def test_restart_never_relaunches_if_executable_changes_after_stop(monkeypatch, tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"original")
    process = FakeProcess(
        executable=str(executable), arguments=["app.exe"], cwd=str(tmp_path)
    )
    _use_process(monkeypatch, process)
    callback, spawned = {}, []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda key, title, detail, run, **_kwargs: callback.update(run=run) or "[CONFIRMATION_PENDING]",
    )
    monkeypatch.setattr(process_master.psutil, "Popen", lambda *a, **kw: spawned.append(a))

    def replace_after_stop(timeout=None):
        executable.write_bytes(b"changed content")
        return 0

    monkeypatch.setattr(process, "wait", replace_after_stop)
    reference = process_master.list_processes()[0]["reference"]
    process_master.restart_process(reference)
    assert "stopped but not restarted" in callback["run"]()
    assert process.stopped
    assert not spawned


def test_restart_reports_spawn_failure_without_leaking_arguments(monkeypatch, tmp_path):
    executable = tmp_path / "app.exe"
    executable.write_bytes(b"original")
    process = FakeProcess(
        executable=str(executable),
        arguments=["app.exe", "private-argument"],
        cwd=str(tmp_path),
    )
    _use_process(monkeypatch, process)
    callback = {}
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda key, title, detail, run, **_kwargs: callback.update(run=run) or "[CONFIRMATION_PENDING]",
    )

    def fail_spawn(*args, **kwargs):
        raise OSError("private-argument")

    monkeypatch.setattr(process_master.psutil, "Popen", fail_spawn)
    reference = process_master.list_processes()[0]["reference"]
    process_master.restart_process(reference)
    result = callback["run"]()
    assert "could not be restarted" in result
    assert "private-argument" not in result
    assert process.stopped


@pytest.mark.parametrize("limit", [0, -1, 201, True, 1.5])
def test_process_listing_rejects_invalid_limits(limit):
    with pytest.raises(ValueError, match="limit"):
        process_master.list_top_processes(limit)


@pytest.mark.parametrize("threshold", [-1, 101, float("nan"), True, "80"])
def test_monitor_hogs_rejects_invalid_thresholds(threshold):
    with pytest.raises(ValueError, match="cpu_threshold"):
        process_master.monitor_hogs(cpu_threshold=threshold)


def test_process_iteration_skips_inaccessible_process(monkeypatch):
    class Inaccessible(FakeProcess):
        def create_time(self):
            raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(
        process_master.psutil, "process_iter",
        lambda: [Inaccessible(pid=1000), FakeProcess(pid=2000)],
    )
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    assert [row["pid"] for row in process_master.list_processes()] == [2000]


def test_pe_signature_check_identifies_unsigned_and_unverified_certificate(tmp_path):
    path = tmp_path / "sample.exe"
    data = bytearray(512)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", data, 0x80 + 20, 0xE0)
    struct.pack_into("<H", data, 0x80 + 24, 0x10B)
    path.write_bytes(data)
    assert process_master._pe_signature_status(str(path)) == "unsigned"

    struct.pack_into("<II", data, 0x80 + 24 + 96 + 32, 480, 16)
    path.write_bytes(data)
    assert process_master._pe_signature_status(str(path)) == "present_unverified"

    struct.pack_into("<II", data, 0x80 + 24 + 96 + 32, 500, 20)
    path.write_bytes(data)
    assert process_master._pe_signature_status(str(path)) == "unknown"
    assert process_master._pe_signature_status(str(tmp_path / "missing.exe")) == "unknown"


def test_service_stop_reports_timeout_and_avoids_duplicate_workers(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def slow_collection(_limit):
        entered.set()
        assert release.wait(5)
        return []

    monkeypatch.setattr(process_master, "list_processes", slow_collection)
    service = process_master.ProcessMaster(refresh_interval=10)
    service.start()
    try:
        assert entered.wait(1)
        worker = service._thread
        service.start()
        assert service._thread is worker
        assert service.stop(timeout=0) is False
    finally:
        release.set()
        assert service.stop(timeout=2) is True


def test_stop_interrupts_enumeration_before_next_process(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    processed = []
    processes = [FakeProcess(pid=4321), FakeProcess(pid=4322)]
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: iter(processes))
    monkeypatch.setattr(process_master, "_poll_status_is_costly", lambda: False)
    protected_calls = []
    monkeypatch.setattr(
        process_master, "_protected_pids",
        lambda: protected_calls.append(True) or set(),
    )
    original = process_master._read_row

    def slow_read(process, protected_pids=None, *, include_status=True):
        processed.append(process.pid)
        entered.set()
        assert release.wait(2)
        return original(process, protected_pids, include_status=include_status)

    monkeypatch.setattr(process_master, "_read_row", slow_read)
    service = process_master.ProcessMaster(refresh_interval=10)
    service.start()
    try:
        assert entered.wait(1)
        assert not service.stop(timeout=0)
        release.set()
        assert service.stop(timeout=2)
        assert processed == [4321]
        assert protected_calls == [True]
        assert service.snapshot()["captured_at"] is None
    finally:
        release.set()
        service.stop(timeout=2)


def test_windows_poll_rotates_bounded_batches_and_drops_exited_pids(monkeypatch):
    processes = {pid: FakeProcess(pid=pid) for pid in range(1000, 1080)}
    monkeypatch.setattr(process_master.psutil, "pids", lambda: list(processes))
    monkeypatch.setattr(process_master.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    monkeypatch.setattr(process_master.time, "thread_time", lambda: 0.0)
    state = process_master._sampling_state
    state.stop_event = threading.Event()
    state.cpu_samples, state.refresh_interval = {}, 10.0
    state.name_cache, state.names = {}, {}
    state.row_cache, state.process_cache, state.cursor = {}, {}, 0
    state.orphan_suspects = {}
    try:
        first = process_master._iter_windows_poll_rows()
        assert len(first) == 32
        assert all(row["status"] == "unknown" for row in first)
        assert len(process_master._iter_windows_poll_rows()) == 64
        assert len(process_master._iter_windows_poll_rows()) == 80
        old_ref = state.row_cache[1000]["reference"]
        processes[1000].stopped = True
        processes[1000] = FakeProcess(pid=1000, created=200.0)
        del processes[1001]
        state.cursor = 0
        rows = process_master._iter_windows_poll_rows()
        assert 1001 not in {row["pid"] for row in rows}
        assert state.row_cache[1000]["reference"] != old_ref
        assert old_ref not in state.names
    finally:
        for key in ("stop_event", "name_cache", "names", "row_cache", "process_cache", "cursor", "orphan_suspects", "cpu_samples", "refresh_interval"):
            delattr(state, key)


def test_facade_service_shared_with_actions_and_snapshot_names_are_local(monkeypatch):
    process = FakeProcess(
        name=r"C:\Users\Private\example.exe", cpu=95, memory=14, status="zombie"
    )
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "_poll_status_is_costly", lambda: False)
    monkeypatch.delenv("JARVIS_SYMBIOSIS", raising=False)
    monkeypatch.delenv("JARVIS_SYMBIOSIS_MODULES", raising=False)
    service = process_master.ProcessMaster(refresh_interval=0.01)
    hub = symbiosis_hub.SymbiosisHub(
        modules={"process"}, factories={"process": lambda: service}
    )
    monkeypatch.setattr(symbiosis_hub, "_hub", hub)
    hub.start()
    try:
        assert service._snapshot_ready.wait(1)
        worker = service._thread
        assert process_master.get_service() is service
        snapshot = service.snapshot()
        assert snapshot["processes"][0]["name"] == "example.exe"
        assert snapshot["top_processes"][0]["ram_percent"] == 14
        assert snapshot["hogs"][0]["name"] == "example.exe"
        assert snapshot["zombies"] is True

        model_rows = json.loads(process_action.list_processes({}))
        assert "name" not in model_rows[0]
        assert "Private" not in json.dumps(model_rows)
        assert service._thread is worker
        assert "name" not in process_master.monitor_hogs()[0]
    finally:
        assert hub.shutdown()


@pytest.mark.parametrize(
    "env_enabled,selected,hub_started",
    [("0", "process", True), ("1", "pulse", True), ("1", "process", False)],
)
def test_process_actions_refuse_when_facade_or_module_inactive(
    monkeypatch, env_enabled, selected, hub_started
):
    monkeypatch.setenv("JARVIS_SYMBIOSIS", env_enabled)
    monkeypatch.setenv("JARVIS_SYMBIOSIS_MODULES", selected)
    process = FakeProcess()
    _use_process(monkeypatch, process)
    service = process_master.ProcessMaster(refresh_interval=0.01)
    hub = symbiosis_hub.SymbiosisHub(
        modules={"process"}, factories={"process": lambda: service}
    )
    monkeypatch.setattr(symbiosis_hub, "_hub", hub)
    if hub_started:
        hub.start()
    try:
        registry = discover_actions(
            Path(__file__).resolve().parents[1] / "actions",
            logger=lambda _message: None,
        )
        for action in (
            "list_processes", "kill_process", "restart_process", "find_zombies",
            "top_ram_processes", "top_cpu_processes", "monitor_hogs", "find_suspicious",
        ):
            result = registry.run(action, {"reference": "anything", "confirmed": True})
            assert "not active" in result
        assert process.stopped is False
    finally:
        assert hub.shutdown()


def test_registry_forged_confirmed_flag_only_opens_hud_gate(monkeypatch):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _message: None
    )
    reference = process_master.list_processes()[0]["reference"]
    response = registry.run(
        "kill_process",
        {"reference": reference, "confirmed": True, "require_confirmation": False},
    )
    assert "[CONFIRMATION_PENDING]" in response
    assert process.stopped is False
    gate.resolve(False)
    assert process.stopped is False


@pytest.mark.parametrize("operation", ["kill_process", "restart_process"])
@pytest.mark.parametrize("model_confirmed", [True, False])
@pytest.mark.parametrize("harness_enabled", [True, False])
def test_jarvis_live_uses_single_hud_confirmation(
    monkeypatch, tmp_path, operation, model_confirmed, harness_enabled
):
    import main
    from core.harness.policy import ApprovalPolicy

    executable = tmp_path / "fake-program.exe"
    executable.write_bytes(b"fixture")
    process = FakeProcess(
        executable=str(executable), arguments=["fake-program.exe", "arg"],
        cwd=str(tmp_path),
    )
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    monkeypatch.setenv("JARVIS_HARNESS", "1" if harness_enabled else "0")
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    shown, logs, spawned = [], [], []
    done = threading.Event()
    monkeypatch.setattr(gate, "_show_cb", lambda title, detail: shown.append((title, detail)))
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    monkeypatch.setattr(gate, "_log_cb", lambda message: (logs.append(message), done.set()))
    monkeypatch.setattr(process_master.psutil, "Popen", lambda *a, **k: spawned.append((a, k)))

    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = SimpleNamespace(
        muted=False, set_state=lambda *_: None, write_log=lambda *_: None
    )
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "stop that process"
    live._local_pending_confirmation = None
    live._action_registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _message: None
    )
    if harness_enabled:
        live._harness_runtime = SimpleNamespace(approval_policy=ApprovalPolicy())
    live._observe_pattern_tool_result = lambda *_args: None
    reference = process_master.list_processes()[0]["reference"]
    call = SimpleNamespace(
        id="process-call", name=operation,
        args={"reference": reference, "confirmed": model_confirmed, "require_confirmation": False},
    )

    response = asyncio.run(live._execute_tool(call))

    assert "[CONFIRMATION_PENDING]" in str(response.response)
    assert len(shown) == 1
    assert process.stopped is False
    done.clear()
    gate.resolve(True)
    assert done.wait(2)
    assert process.stopped is True
    assert len(shown) == 1
    assert len(spawned) == (1 if operation == "restart_process" else 0)


@pytest.mark.parametrize("change", ["protected", "pid_reused"])
def test_jarvis_hud_confirmation_revalidates_target(monkeypatch, change):
    import main

    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    monkeypatch.setenv("JARVIS_HARNESS", "0")
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    logs, done = [], threading.Event()

    def log_result(message):
        logs.append(message)
        if "SYS: Confirmed" in message:
            done.set()

    monkeypatch.setattr(gate, "_log_cb", log_result)
    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = SimpleNamespace(muted=False, set_state=lambda *_: None, write_log=lambda *_: None)
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "stop this"
    live._local_pending_confirmation = None
    live._action_registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _message: None
    )
    live._harness_approval_decision = lambda *_args: None
    live._observe_pattern_tool_result = lambda *_args: None
    reference = process_master.list_processes()[0]["reference"]
    response = asyncio.run(live._execute_tool(SimpleNamespace(
        id="process-call", name="kill_process",
        args={"reference": reference, "confirmed": True},
    )))
    assert "[CONFIRMATION_PENDING]" in str(response.response)
    if change == "protected":
        process._name = "lsass.exe"
    else:
        process.created += 0.0001
    gate.resolve(True)
    assert done.wait(2)
    assert not process.stopped
    assert any("protected" in log or "no longer the same process" in log for log in logs)


def test_concurrent_confirmation_requests_cannot_replace_the_original(monkeypatch):
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()
    shown, executed = [], []

    def show(title, _detail):
        shown.append(title)
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(gate, "_show_cb", show)
    results = []
    thread = threading.Thread(target=lambda: results.append(
        gate.request("first", "First process", "terminate", lambda: (
            executed.append("first"), completed.set(), "done"
        )[-1])
    ))
    thread.start()
    try:
        assert entered.wait(1)
        second = gate.request(
            "second", "Different process", "restart", lambda: executed.append("second")
        )
        assert "already pending" in second
    finally:
        release.set()
        thread.join(2)
    assert "[CONFIRMATION_PENDING]" in results[0]
    assert shown == ["First process"]
    gate.resolve(True)
    assert completed.wait(1)
    assert executed == ["first"]


def test_expired_banner_cannot_be_replaced_before_user_resolves_it(monkeypatch):
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    now = [100.0]
    monkeypatch.setattr(gate.time, "monotonic", lambda: now[0])
    executed = []
    gate.request("first", "Old", "terminate", lambda: executed.append("old"))
    now[0] += gate.TIMEOUT_SECONDS + 1
    assert "already pending" in gate.request(
        "second", "New", "restart", lambda: executed.append("new")
    )
    gate.resolve(True)
    assert executed == []
    assert "[CONFIRMATION_PENDING]" in gate.request(
        "second", "New", "restart", lambda: executed.append("new")
    )
    gate.resolve(False)
    assert executed == []


def test_untrusted_handler_named_kill_process_cannot_skip_outer_gate():
    import main

    rec = SimpleNamespace(
        valid=True, risk_class="destructive", file="kill_process.py",
        handler=lambda parameters: "unsafe",
    )
    live = main.JarvisLive.__new__(main.JarvisLive)
    live._action_registry = SimpleNamespace(
        _actions={"kill_process": rec},
        has=lambda name: name == "kill_process",
        risk_class=lambda _name: "destructive",
    )
    assert not live._process_hud_confirmation_delegated("kill_process")
    assert live._action_requires_confirmation("kill_process", {})


def test_jarvis_pending_process_action_cannot_be_replaced(monkeypatch, tmp_path):
    import main

    executable = tmp_path / "fake-program.exe"
    executable.write_bytes(b"fixture")
    first = FakeProcess(pid=4321)
    second = FakeProcess(
        pid=4322, executable=str(executable), arguments=["fake-program.exe"],
        cwd=str(tmp_path),
    )
    processes = {first.pid: first, second.pid: second}
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: list(processes.values()))
    monkeypatch.setattr(process_master.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    monkeypatch.setenv("JARVIS_HARNESS", "0")
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_pending", None)
    shown, spawned = [], []
    finished = threading.Event()
    monkeypatch.setattr(gate, "_show_cb", lambda title, detail: shown.append((title, detail)))
    monkeypatch.setattr(gate, "_hide_cb", lambda: None)

    def log_result(message):
        if "SYS: Confirmed" in message:
            finished.set()

    monkeypatch.setattr(gate, "_log_cb", log_result)
    monkeypatch.setattr(process_master.psutil, "Popen", lambda *a, **k: spawned.append((a, k)))
    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = SimpleNamespace(muted=False, set_state=lambda *_: None, write_log=lambda *_: None)
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "stop this"
    live._local_pending_confirmation = None
    live._action_registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _message: None
    )
    live._observe_pattern_tool_result = lambda *_args: None
    references = {
        row["pid"]: row["reference"] for row in process_master.list_processes()
    }

    async def request_both():
        response1 = await live._execute_tool(SimpleNamespace(
            id="first", name="kill_process", args={"reference": references[first.pid]}
        ))
        response2 = await live._execute_tool(SimpleNamespace(
            id="second", name="restart_process", args={"reference": references[second.pid]}
        ))
        return response1, response2

    response1, response2 = asyncio.run(request_both())
    assert "[CONFIRMATION_PENDING]" in str(response1.response)
    assert "confirmation is pending" in str(response2.response)
    assert len(shown) == 1
    assert not first.stopped and not second.stopped
    gate.resolve(True)
    assert finished.wait(2)
    assert first.stopped and not second.stopped
    assert spawned == []


@pytest.mark.parametrize(
    ("words", "stopped"),
    [("confermo", True), ("annulla", False), ("non confermo", False)],
)
def test_fresh_local_voice_turn_resolves_only_matching_process(
    monkeypatch, words, stopped
):
    import main

    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_keyed_bind", True)
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda *_: None)
    finished = threading.Event()
    transcripts = []

    def log_result(message):
        if "Confirmed" in message or "Cancelled" in message:
            finished.set()

    class FakeSTT:
        def __init__(self, **options):
            assert options["local_files_only"] is True

        def transcribe(self, audio):
            transcripts.append(audio.copy())
            return words

    monkeypatch.setattr(gate, "_log_cb", log_result)
    monkeypatch.setattr(main, "WhisperSTT", FakeSTT)
    reference = process_master.list_processes()[0]["reference"]
    assert "[CONFIRMATION_PENDING]" in process_master.kill_process(reference)
    capture = main._ProcessVoiceCapture()
    silence = np.zeros(1024, dtype=np.int16)
    speech = np.full(1024, 3000, dtype=np.int16)
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=time.monotonic())
    if words == "non confermo":
        deadline = time.monotonic() + 2
        while capture._working and time.monotonic() < deadline:
            time.sleep(0.01)
        assert gate.process_voice_candidate() is not None
        gate.resolve(False, key=gate.process_voice_candidate()[0])
    assert finished.wait(2)
    assert process.stopped is stopped
    assert len(transcripts) == 1
    assert gate.process_voice_candidate() is None


def test_voice_capture_rejects_stale_audio_and_old_transcription(monkeypatch):
    import main

    gate = process_master.confirm
    monkeypatch.setattr(gate, "_keyed_bind", True)
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    blocked, release = threading.Event(), threading.Event()
    executed = []

    class SlowSTT:
        def __init__(self, **_kwargs):
            pass

        def transcribe(self, _audio):
            blocked.set()
            assert release.wait(2)
            return "confermo"

    monkeypatch.setattr(main, "WhisperSTT", SlowSTT)
    stale = time.monotonic()
    gate.request(
        "process-master-first", "first", "detail", lambda: executed.append("first"),
        process_voice=True,
    )
    capture = main._ProcessVoiceCapture()
    silence = np.zeros(1024, dtype=np.int16)
    speech = np.full(1024, 3000, dtype=np.int16)
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=stale)
    assert not blocked.is_set()
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=time.monotonic())
    assert blocked.wait(2)
    first_key = gate.process_voice_candidate()[0]
    gate.resolve(False, key=first_key)
    gate.request(
        "process-master-second", "second", "detail", lambda: executed.append("second"),
        process_voice=True,
    )
    release.set()
    deadline = time.monotonic() + 2
    while capture._working and time.monotonic() < deadline:
        time.sleep(0.01)
    assert executed == []
    second_key = gate.process_voice_candidate()[0]
    assert second_key != first_key
    gate.resolve(False, key=second_key)


def test_voice_does_not_resolve_other_gates_or_speech_without_silence(monkeypatch):
    import main

    gate = process_master.confirm
    monkeypatch.setattr(gate, "_keyed_bind", True)
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_log_cb", None)
    monkeypatch.setattr(
        main, "WhisperSTT", lambda **_kwargs: pytest.fail("must not transcribe")
    )
    capture = main._ProcessVoiceCapture()
    speech = np.full(1024, 3000, dtype=np.int16)
    gate.request("process-master-other", "other", "detail", lambda: None)
    other_key = gate._pending.token
    for _ in range(30):
        capture.feed(speech, allowed=True, speaking=False, captured_at=time.monotonic())
    assert gate.process_voice_candidate() is None
    gate.resolve(False, key=other_key)
    gate.request(
        "process-master-valid", "process", "detail", lambda: None, process_voice=True
    )
    for _ in range(30):
        capture.feed(speech, allowed=True, speaking=False, captured_at=time.monotonic())
    assert gate.process_voice_candidate() is not None
    gate.resolve(False, key=gate.process_voice_candidate()[0])


@pytest.mark.parametrize("selector", [4321, "4321", "sample.exe"])
def test_core_pid_and_name_require_confirmation_and_check_reuse(monkeypatch, selector):
    process = FakeProcess()
    _use_process(monkeypatch, process)
    callbacks = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda _key, _title, _detail, run, **_kwargs: (
            callbacks.append(run) or "[CONFIRMATION_PENDING]"
        ),
    )
    assert "[CONFIRMATION_PENDING]" in process_master.kill_process(
        selector, require_confirmation=False
    )
    assert not process.stopped
    process.created += 1
    assert "no longer the same" in callbacks[0]()
    assert not process.stopped


def test_name_ambiguity_and_changed_name_are_rejected(monkeypatch):
    first, second = FakeProcess(), FakeProcess(pid=5555)
    _use_process(monkeypatch, first)
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [first, second])
    assert "ambiguous" in process_master.kill_process("sample.exe")
    assert not first.stopped and not second.stopped
    monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [first])
    callbacks = []
    monkeypatch.setattr(process_master.confirm, "pending_title", lambda: "")
    monkeypatch.setattr(
        process_master.confirm, "request",
        lambda _key, _title, _detail, run, **_kwargs: (
            callbacks.append(run) or "[CONFIRMATION_PENDING]"
        ),
    )
    assert "[CONFIRMATION_PENDING]" in process_master.kill_process("sample.exe")
    first._name = "other.exe"
    assert "no longer the same" in callbacks[0]()
    assert not first.stopped


def test_windows_poll_orphans_require_two_verified_samples(monkeypatch):
    orphan = FakeProcess(pid=4321, ppid=9999)
    protected = FakeProcess(pid=12, ppid=9999)
    missing_parent = False
    processes = {p.pid: p for p in (orphan, protected)}
    monkeypatch.setattr(process_master.psutil, "pids", lambda: list(processes))
    monkeypatch.setattr(process_master.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(process_master.psutil, "pid_exists", lambda _pid: not missing_parent)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    state = process_master._sampling_state
    state.stop_event = threading.Event()
    state.cpu_samples, state.refresh_interval = {}, 10.0
    state.name_cache, state.names = {}, {}
    state.row_cache, state.process_cache, state.orphan_suspects, state.cursor = {}, {}, {}, 0
    try:
        process_master._iter_windows_poll_rows()
        assert state.row_cache[4321]["status"] == "unknown"
        missing_parent = True
        process_master._iter_windows_poll_rows()
        assert state.row_cache[4321]["status"] == "unknown"
        process_master._iter_windows_poll_rows()
        assert state.row_cache[4321]["status"] == "orphan"
        assert state.row_cache[12]["status"] == "unknown"
        missing_parent = False
        process_master._iter_windows_poll_rows()
        assert state.row_cache[4321]["status"] == "unknown"
    finally:
        for key in ("stop_event", "name_cache", "names", "row_cache", "process_cache",
                    "orphan_suspects", "cursor", "cpu_samples", "refresh_interval"):
            delattr(state, key)


def test_poll_failure_is_logged_without_sensitive_error_and_snapshot_fails_closed(
    monkeypatch, caplog
):
    def fail(_limit):
        raise OSError(r"C:\Users\private\secret.exe")

    monkeypatch.setattr(process_master, "list_processes", fail)
    service = process_master.ProcessMaster(refresh_interval=10)
    service.start()
    try:
        assert service._snapshot_ready.wait(2)
        snapshot = service.snapshot()
        assert snapshot["error"] == "OSError"
        assert snapshot["captured_at"] is None
        assert snapshot["zombies"] is None
        assert snapshot["processes"] == []
        assert "[SYMBIOSIS][PROCESS]" in caplog.text
        assert "secret.exe" not in caplog.text and "private" not in caplog.text
    finally:
        assert service.stop()


def test_windows_hog_priority_refresh_and_failed_read(monkeypatch):
    processes = {pid: FakeProcess(pid=pid) for pid in range(1000, 1080)}
    processes[1079]._cpu = 95
    reads = []
    monkeypatch.setattr(process_master.psutil, "pids", lambda: list(processes))
    monkeypatch.setattr(process_master.psutil, "pid_exists", lambda _pid: True)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    monkeypatch.setattr(process_master.time, "thread_time", lambda: 0.0)
    clock = [1000.0]
    monkeypatch.setattr(process_master.time, "time", lambda: clock[0])

    def get_process(pid):
        reads.append(pid)
        return processes[pid]

    monkeypatch.setattr(process_master.psutil, "Process", get_process)
    state = process_master._sampling_state
    state.stop_event = threading.Event()
    state.cpu_samples, state.refresh_interval = {}, 10.0
    state.name_cache, state.names = {}, {}
    state.row_cache, state.process_cache, state.orphan_suspects, state.cursor = {}, {}, {}, 79
    try:
        process_master._iter_windows_poll_rows()
        assert state.row_cache[1079]["observed_at"] == 1000
        clock[0] = 1010
        reads.clear()
        process_master._iter_windows_poll_rows()
        assert state.row_cache[1079]["observed_at"] == 1010
        assert 1079 in state.row_cache
        processes[1079].create_time = lambda: (_ for _ in ()).throw(psutil.AccessDenied())
        process_master._iter_windows_poll_rows()
        assert 1079 not in state.row_cache
    finally:
        for key in ("stop_event", "name_cache", "names", "row_cache", "process_cache",
                    "orphan_suspects", "cursor", "cpu_samples", "refresh_interval"):
            delattr(state, key)


def test_snapshot_marks_stale_and_excludes_stale_hogs(monkeypatch):
    monkeypatch.setattr(process_master.time, "time", lambda: 1000.0)
    service = process_master.ProcessMaster(refresh_interval=10)
    service._snapshot = {
        "captured_at": 1000.0, "error": None, "zombies": False,
        "processes": [
            {"pid": 300, "reference": "fresh", "status": "unknown", "name": None,
             "observed_at": 995.0, "cpu_percent": 90, "memory_percent": 0, "protected": False,
             "cpu_high_for_seconds": 30.0},
            {"pid": 301, "reference": "stale", "status": "unknown", "name": None,
             "observed_at": 970.0, "cpu_percent": 95, "memory_percent": 0, "protected": False,
             "cpu_high_for_seconds": 100.0},
        ],
    }
    snapshot = service.snapshot()
    assert [row["stale"] for row in snapshot["processes"]] == [False, True]
    assert [row["reference"] for row in snapshot["hogs"]] == ["fresh"]
    assert snapshot["hogs"][0]["cpu_high_for_seconds"] == 30.0
    assert snapshot["processes"][1]["cpu_high_for_seconds"] == 0.0
    assert service.snapshot()["hogs"][0]["cpu_high_for_seconds"] == 30.0
    assert snapshot["top_processes"][1]["observed_at"] == 970.0


def test_windows_cpu_high_continuity_gap_recovery_and_pid_reuse(monkeypatch):
    process = FakeProcess(cpu=90)
    processes = {process.pid: process}
    clock = [1000.0]
    monkeypatch.setattr(process_master.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(process_master.time, "time", lambda: clock[0])
    monkeypatch.setattr(process_master.time, "thread_time", lambda: 0.0)
    monkeypatch.setattr(process_master.psutil, "pids", lambda: list(processes))
    monkeypatch.setattr(process_master.psutil, "Process", lambda pid: processes[pid])
    monkeypatch.setattr(process_master.psutil, "pid_exists", lambda _pid: True)
    monkeypatch.setattr(process_master, "_protected_pids", lambda: set())
    state = process_master._sampling_state
    state.stop_event = threading.Event()
    state.name_cache, state.names = {}, {}
    state.row_cache, state.process_cache, state.orphan_suspects, state.cursor = {}, {}, {}, 0
    state.cpu_samples, state.refresh_interval = {}, 10.0
    try:
        def sample(at):
            clock[0] = at
            return dict(process_master._iter_windows_poll_rows()[0])

        assert sample(1000)["cpu_high_for_seconds"] == 0
        assert sample(1010)["cpu_high_for_seconds"] == 10
        assert sample(1030)["cpu_high_for_seconds"] == 30

        # A long collection gap followed by a fresh row before the next consumer tick.
        resumed = sample(1051)
        assert resumed["observed_at"] == 1051
        assert resumed["cpu_high_for_seconds"] == 0
        assert sample(1061)["cpu_high_for_seconds"] == 10
        process._cpu = 80
        assert sample(1071)["cpu_high_for_seconds"] == 0
        process._cpu = 90
        assert sample(1081)["cpu_high_for_seconds"] == 0
        assert sample(1091)["cpu_high_for_seconds"] == 10
        process.created += 1
        replacement = sample(1101)
        assert replacement["reference"] != resumed["reference"]
        assert replacement["cpu_high_for_seconds"] == 0
        assert sample(1111)["cpu_high_for_seconds"] == 10
        process.create_time = lambda: (_ for _ in ()).throw(psutil.AccessDenied())
        clock[0] = 1121
        assert process_master._iter_windows_poll_rows() == []
        assert process.pid not in state.cpu_samples
    finally:
        for key in ("stop_event", "name_cache", "names", "row_cache", "process_cache",
                    "orphan_suspects", "cursor", "cpu_samples", "refresh_interval"):
            delattr(state, key)


def test_unix_poll_records_only_real_samples_and_resets_after_failure(monkeypatch):
    process = FakeProcess(cpu=90)
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "_poll_status_is_costly", lambda: False)
    clock = [1000.0]
    monkeypatch.setattr(process_master.time, "monotonic", lambda: clock[0])
    state = process_master._sampling_state
    state.stop_event = threading.Event()
    state.name_cache, state.names = {}, {}
    state.cpu_samples, state.refresh_interval = {}, 10.0
    try:
        assert process_master._iter_process_rows()[0]["cpu_high_for_seconds"] == 0
        clock[0] += 10
        assert process_master._iter_process_rows()[0]["cpu_high_for_seconds"] == 10
        monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [])
        assert process_master._iter_process_rows() == []
        monkeypatch.setattr(process_master.psutil, "process_iter", lambda: [process])
        clock[0] += 10
        assert process_master._iter_process_rows()[0]["cpu_high_for_seconds"] == 0
    finally:
        for key in ("stop_event", "name_cache", "names", "cpu_samples", "refresh_interval"):
            delattr(state, key)


@pytest.mark.parametrize("outcome", ["confirm", "cancel", "reuse"])
def test_jarvis_live_single_local_voice_confirmation(monkeypatch, outcome):
    import main

    process = FakeProcess()
    _use_process(monkeypatch, process)
    monkeypatch.setattr(process_master, "get_service", lambda: object())
    monkeypatch.setenv("JARVIS_HARNESS", "0")
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    monkeypatch.setattr(main, "route_tool", lambda *_args: None)
    gate = process_master.confirm
    monkeypatch.setattr(gate, "_keyed_bind", True)
    done = threading.Event()
    monkeypatch.setattr(gate, "_pending", None)
    monkeypatch.setattr(gate, "_show_cb", lambda *_: None)
    monkeypatch.setattr(gate, "_hide_cb", lambda *_: None)

    def log_result(message):
        if "Confirmed" in message or "Cancelled" in message:
            done.set()

    monkeypatch.setattr(gate, "_log_cb", log_result)

    class LocalSTT:
        def __init__(self, **options):
            assert options["local_files_only"]

        def transcribe(self, _audio):
            return "annulla" if outcome == "cancel" else "confermo"

    monkeypatch.setattr(main, "WhisperSTT", LocalSTT)
    live = main.JarvisLive.__new__(main.JarvisLive)
    live.ui = SimpleNamespace(muted=False, set_state=lambda *_: None, write_log=lambda *_: None)
    live._asst_name = "JARVIS"
    live._brain_router = SimpleNamespace(backend="local")
    live._last_user_text = "stop this"
    live._local_pending_confirmation = None
    live._action_registry = discover_actions(
        Path(__file__).resolve().parents[1] / "actions", logger=lambda _message: None
    )
    live._harness_approval_decision = lambda *_args: None
    live._observe_pattern_tool_result = lambda *_args: None
    reference = process_master.list_processes()[0]["reference"]
    response = asyncio.run(live._execute_tool(SimpleNamespace(
        id="process-call", name="kill_process",
        args={"reference": reference, "confirmed": True},
    )))
    assert "[CONFIRMATION_PENDING]" in str(response.response)
    assert not process.stopped
    if outcome == "reuse":
        process.created += 1
    capture = main._ProcessVoiceCapture()
    silence = np.zeros(1024, dtype=np.int16)
    speech = np.full(1024, 3000, dtype=np.int16)
    for frame in [silence] * 7 + [speech] * 4 + [silence] * 10:
        capture.feed(frame, allowed=True, speaking=False, captured_at=time.monotonic())
    assert done.wait(2)
    assert process.stopped is (outcome == "confirm")
    assert gate.process_voice_candidate() is None

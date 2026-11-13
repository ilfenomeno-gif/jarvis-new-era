from __future__ import annotations

import ctypes
import json
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from actions import _multi_monitor_support as monitor_action_support
from actions import arrange_windows as arrange_action
from actions import get_active_monitor as active_action
from actions import list_monitors as list_action
from actions import move_window_to_monitor as move_action
from actions import restore_layout as restore_action
from actions import save_layout as save_action
from core import multi_monitor as mm

_MONITOR_A = {
    "index": 0,
    "left": 0,
    "top": 0,
    "width": 1920,
    "height": 1080,
    "resolution": "1920x1080",
    "dpi_x": 96,
    "dpi_y": 96,
    "primary": True,
}
_MONITOR_B = {
    "index": 1,
    "left": -1280,
    "top": 0,
    "width": 1280,
    "height": 1024,
    "resolution": "1280x1024",
    "dpi_x": 120,
    "dpi_y": 120,
    "primary": False,
}


class _MssContext:
    monitors = [
        {"left": -1280, "top": 0, "width": 3200, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": -1280, "top": 0, "width": 1280, "height": 1024},
    ]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _window(hwnd=101, title="Private title", pid=1234, process_name="notepad.exe",
            left=20, top=30, width=400, height=300):
    return {
        "hwnd": hwnd,
        "title": title,
        "pid": pid,
        "process_name": process_name,
        "left": left,
        "top": top,
        "width": width,
        "height": height,
    }


def test_list_monitors_returns_coordinates_resolution_and_dpi_without_titles(monkeypatch):
    monkeypatch.setattr(mm, "_require_windows", lambda: None)
    monkeypatch.setattr(mm, "_load_mss", lambda: SimpleNamespace(mss=_MssContext))
    monkeypatch.setattr(mm, "_monitor_dpi", lambda *_args: (120, 120))

    monitors = mm.list_monitors()

    assert monitors == [
        {**_MONITOR_A, "dpi_x": 120, "dpi_y": 120},
        {**_MONITOR_B, "dpi_x": 120, "dpi_y": 120},
    ]
    assert all(not ({"title", "path", "pid"} & monitor.keys()) for monitor in monitors)


def test_list_monitors_handles_missing_optional_dependency(monkeypatch):
    monkeypatch.setattr(mm, "_require_windows", lambda: None)
    monkeypatch.setattr(
        mm, "_load_mss",
        lambda: (_ for _ in ()).throw(mm.MultiMonitorError("mss unavailable")),
    )

    with pytest.raises(mm.MultiMonitorError, match="mss unavailable"):
        mm.list_monitors()


@pytest.mark.parametrize("pid,name", [(99, "notepad.exe"), (1234, "svchost.exe")])
def test_move_window_refuses_system_and_low_pid_targets(monkeypatch, pid, name):
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [
        _window(pid=pid, process_name=name),
    ])
    monkeypatch.setattr(
        mm, "_place_window",
        lambda *_args: pytest.fail("Protected process reached placement."),
    )

    with pytest.raises(mm.MultiMonitorError, match="protected processes"):
        mm.move_window_to_monitor("Private title", 0)


def test_move_window_to_monitor_uses_title_only_for_selection(monkeypatch):
    placement = []
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window()])
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_place_window", lambda *args: placement.append(args))

    result = mm.move_window_to_monitor("Private title", 0)

    assert result == {"ok": True, "monitor_index": 0}
    assert placement == [(101, 760, 390, 400, 300)]
    assert "Private title" not in str(result)


def test_move_window_rejects_ambiguous_titles_without_leaking_title(monkeypatch):
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window(), _window(hwnd=102)])

    with pytest.raises(mm.MultiMonitorError, match="multiple windows") as exc:
        mm.move_window_to_monitor("Private title", 0)
    assert "Private title" not in str(exc.value)


def test_get_active_monitor_uses_foreground_window_geometry_only(monkeypatch):
    monkeypatch.setattr(mm, "_foreground_window", lambda: (101, 1234))
    monkeypatch.setattr(mm, "_is_protected_process", lambda _pid: False)
    monkeypatch.setattr(mm, "_rect_for_window", lambda _hwnd: (-1200, 100, -800, 500))
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A, _MONITOR_B])

    active = mm.get_active_monitor()

    assert active == _MONITOR_B
    assert "title" not in active


@pytest.mark.parametrize("layout", ["grid", "cascade", "left-right"])
def test_arrange_windows_supports_each_layout_and_returns_no_window_data(monkeypatch, layout):
    placements = []
    windows = [
        _window(hwnd=101, left=10),
        _window(hwnd=102, left=20, title="Another private title"),
    ]
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: windows)
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_place_window", lambda *args: placements.append(args))

    result = mm.arrange_windows(layout, monitor_index=0)

    assert result == {"ok": True, "layout": layout, "monitor_index": 0, "arranged": 2}
    assert len(placements) == 2
    assert "private" not in str(result).casefold()
    if layout == "left-right":
        assert placements[0][1:] == (0, 0, 960, 1080)
        assert placements[1][1:] == (960, 0, 960, 1080)


def test_arrange_windows_rechecks_protected_pid(monkeypatch):
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window(pid=99)])
    monkeypatch.setattr(
        mm, "_place_window",
        lambda *_args: pytest.fail("Protected process reached placement."),
    )

    with pytest.raises(mm.MultiMonitorError, match="protected processes"):
        mm.arrange_windows("cascade", 0)


def test_save_and_restore_layout_keep_personal_identifiers_hashed(monkeypatch):
    storage = Path(__file__).with_name(".monitor-layout-test.json")
    storage.unlink(missing_ok=True)
    windows = [_window(title="Someone's confidential document")]
    placements = []
    monkeypatch.setattr(mm, "_layout_path", lambda: storage)
    monitor_state = {"monitor": _MONITOR_A}
    monkeypatch.setattr(mm, "list_monitors", lambda: [monitor_state["monitor"]])
    monkeypatch.setattr(mm, "_enum_windows", lambda: windows)
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_place_window", lambda *args: placements.append(args))
    try:
        saved = mm.save_layout("private named layout")
        serialized = storage.read_text(encoding="utf-8")
        monitor_state["monitor"] = {
            **_MONITOR_A,
            "left": -100,
            "width": 3840,
            "height": 2160,
            "resolution": "3840x2160",
            "dpi_x": 192,
            "dpi_y": 192,
        }
        restored = mm.restore_layout("private named layout")
    finally:
        storage.unlink(missing_ok=True)

    assert saved == {"ok": True, "saved": 1}
    assert restored == {"ok": True, "restored": 1}
    assert "Someone's confidential document" not in serialized
    assert "notepad.exe" not in serialized
    assert "private named layout" not in serialized
    assert placements == [(101, -60, 60, 800, 600)]


def test_restore_layout_protects_low_pid_windows(monkeypatch):
    storage = Path(__file__).with_name(".monitor-layout-test.json")
    storage.write_text(
        json.dumps({
            "version": mm.LAYOUT_VERSION,
            "layouts": {
                mm._digest("default"): [{
                    "title_hash": mm._digest("private title"),
                    "process_hash": mm._digest("notepad.exe"),
                    "left": 0,
                    "top": 0,
                    "width": 300,
                    "height": 200,
                    "monitor_index": 0,
                }],
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(mm, "_layout_path", lambda: storage)
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window(pid=99)])
    monkeypatch.setattr(
        mm, "_place_window",
        lambda *_args: pytest.fail("Protected process reached placement."),
    )
    try:
        assert mm.restore_layout() == {"ok": True, "restored": 0}
    finally:
        storage.unlink(missing_ok=True)


def test_manager_hotplug_increments_change_counter_and_hides_extra_fields():
    state = {"monitors": [_MONITOR_A], "active": _MONITOR_A}
    manager = mm.MultiMonitorManager(
        poll_interval=0.01,
        monitor_provider=lambda: [dict(state["monitors"][0], title="private title")]
        if len(state["monitors"]) == 1
        else [dict(monitor, title="private title") for monitor in state["monitors"]],
        active_monitor_provider=lambda: dict(state["active"], path="private path"),
    )
    initial = manager.start()
    snapshot = initial
    state["monitors"] = [_MONITOR_A, _MONITOR_B]
    state["active"] = _MONITOR_B
    deadline = time.monotonic() + 1
    try:
        while time.monotonic() < deadline:
            snapshot = manager.snapshot()
            if len(snapshot["monitors"]) == 2:
                break
            time.sleep(0.01)
    finally:
        assert manager.stop(timeout=1) is True

    assert initial["change_counter"] >= 1
    assert snapshot["change_counter"] > initial["change_counter"]
    assert snapshot["active_monitor"]["index"] == 1
    assert len(snapshot["monitors"]) == 2
    assert "private" not in str(snapshot).casefold()
    assert set(snapshot) == {
        "available", "monitors", "active_monitor", "change_counter", "error",
    }


def test_manager_stop_obeys_timeout_and_returns_false_while_poll_is_running():
    release = mm.threading.Event()
    provider_entered = mm.threading.Event()
    state = {"block": False}

    def provider():
        if state["block"]:
            provider_entered.set()
            release.wait(1)
        return [_MONITOR_A]

    manager = mm.MultiMonitorManager(
        poll_interval=0.01,
        monitor_provider=provider,
        active_monitor_provider=lambda: _MONITOR_A,
    )
    manager.start()
    state["block"] = True
    assert provider_entered.wait(1)
    assert manager.stop(timeout=0) is False
    release.set()
    assert manager.stop(timeout=1) is True


def test_action_files_register_the_six_requested_tool_names():
    modules = [
        active_action,
        list_action,
        move_action,
        arrange_action,
        save_action,
        restore_action,
    ]
    assert [module.TOOL["name"] for module in modules] == [
        "get_active_monitor",
        "list_monitors",
        "move_window_to_monitor",
        "arrange_windows",
        "save_layout",
        "restore_layout",
    ]
    assert len({module.TOOL["name"] for module in modules}) == 6


def test_action_results_do_not_include_window_title(monkeypatch):
    monkeypatch.setattr(move_action, "move_window_to_monitor", lambda **_kwargs: {
        "ok": True, "monitor_index": 0,
    })
    monkeypatch.setattr(
        monitor_action_support,
        "get_symbiosis_hub",
        lambda *, start=False: SimpleNamespace(
            get_module=lambda name: SimpleNamespace(snapshot=lambda: {
                "available": True, "monitors": [_MONITOR_A],
                "active_monitor": _MONITOR_A, "change_counter": 1, "error": None,
            }) if name == "monitor" else None,
        ),
    )

    result = move_action.run({"window_title": "Private title", "monitor_index": 0})

    assert result == {"ok": True, "monitor_index": 0}
    assert "Private title" not in str(result)


@pytest.mark.parametrize(
    "hub, message",
    [
        (None, "hub is not initialized"),
        (SimpleNamespace(get_module=lambda _name: None), "monitor module is not active"),
    ],
)
def test_monitor_actions_require_active_facade_module(monkeypatch, hub, message):
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "1")
    monkeypatch.setattr(monitor_action_support, "get_symbiosis_hub", lambda *, start=False: hub)
    result = list_action.run({})
    assert result["ok"] is False
    assert message in result["error"]


def test_monitor_actions_explain_disabled_symbiosis(monkeypatch):
    monkeypatch.setenv("JARVIS_SYMBIOSIS", "0")
    monkeypatch.setattr(
        monitor_action_support, "get_symbiosis_hub",
        lambda *, start=False: None,
    )
    result = list_action.run({})
    assert result == {
        "ok": False,
        "error": "Symbiosis is disabled (JARVIS_SYMBIOSIS=0); enable it to use monitor actions.",
    }


def test_actions_use_facade_snapshot_and_do_not_start_manager(monkeypatch):
    calls = []

    class FacadeMonitor:
        def snapshot(self):
            return {
                "available": True,
                "monitors": [_MONITOR_A],
                "active_monitor": _MONITOR_A,
                "change_counter": 7,
                "error": None,
            }

        def start(self):
            pytest.fail("An action must not start a parallel manager thread.")

    manager = FacadeMonitor()
    hub = SimpleNamespace(get_module=lambda name: manager if name == "monitor" else None)

    def get_hub(*, start):
        calls.append(start)
        return hub

    monkeypatch.setattr(monitor_action_support, "get_symbiosis_hub", get_hub)
    assert list_action.run({}) == {"ok": True, "monitors": [_MONITOR_A]}
    assert active_action.run({}) == {"ok": True, "active_monitor": _MONITOR_A}
    assert calls == [False, False]


def test_platform_guard_reports_non_windows(monkeypatch):
    monkeypatch.setattr(mm.sys, "platform", "linux")
    with pytest.raises(mm.MultiMonitorError, match="only on Windows"):
        mm._require_windows()


def test_load_psutil_and_process_inspection_fail_closed(monkeypatch):
    monkeypatch.setattr(
        mm, "_load_psutil",
        lambda: (_ for _ in ()).throw(mm.MultiMonitorError("missing")),
    )
    assert mm._is_protected_process(1234) is True
    with pytest.raises(mm.MultiMonitorError, match="missing"):
        mm._process_name(1234)


def test_process_name_normalizes_and_protection_checks_names(monkeypatch):
    class Process:
        def __init__(self, _pid):
            pass

        def name(self):
            return "Notepad.EXE"

    monkeypatch.setattr(mm, "_load_psutil", lambda: SimpleNamespace(Process=Process))
    assert mm._process_name(1234) == "notepad.exe"
    assert mm._is_protected_process(1234) is False
    assert mm._is_protected_process(1) is True
    assert mm._is_protected_process(1234, "LSASS.EXE") is True


def test_load_mss_and_win32gui_wrap_missing_dependencies(monkeypatch):
    real_import = __import__

    def missing_mss(name, *args, **kwargs):
        if name in {"mss", "win32gui"}:
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", missing_mss)
    with pytest.raises(mm.MultiMonitorError, match="optional mss"):
        mm._load_mss()
    with pytest.raises(mm.MultiMonitorError, match="pywin32"):
        mm._load_win32gui()


def test_monitor_dpi_returns_dpi_and_falls_back_to_unknown(monkeypatch):
    from ctypes import wintypes

    class User32:
        def MonitorFromPoint(self, _point, _flags):
            return 42

        def SetThreadDpiAwarenessContext(self, _context):
            return 1

    class Shcore:
        status = 0

        def GetDpiForMonitor(self, _handle, _kind, x_ptr, y_ptr):
            if self.status:
                return self.status
            ctypes.cast(x_ptr, ctypes.POINTER(wintypes.UINT)).contents.value = 144
            ctypes.cast(y_ptr, ctypes.POINTER(wintypes.UINT)).contents.value = 120
            return 0

    shcore = Shcore()
    monkeypatch.setattr(mm, "_windows_user32", lambda: User32())
    monkeypatch.setattr(mm.ctypes, "windll", SimpleNamespace(shcore=shcore), raising=False)
    assert mm._monitor_dpi(0, 0, 100, 100) == (144, 120)
    shcore.status = 1
    assert mm._monitor_dpi(0, 0, 100, 100) == (None, None)


@pytest.mark.parametrize(
    "raw, message",
    [
        ([], "No physical displays"),
        ([{"left": 0, "top": 0, "width": 0, "height": 10}], "invalid monitor dimensions"),
        ([{"left": 0, "top": 0, "width": "bad", "height": 10}], "invalid monitor information"),
    ],
)
def test_list_monitors_rejects_empty_or_invalid_geometry(monkeypatch, raw, message):
    class Context(_MssContext):
        monitors = [{"left": 0, "top": 0, "width": 100, "height": 100}, *raw]

    monkeypatch.setattr(mm, "_require_windows", lambda: None)
    monkeypatch.setattr(mm, "_load_mss", lambda: SimpleNamespace(mss=Context))
    with pytest.raises(mm.MultiMonitorError, match=message):
        mm.list_monitors()


def test_list_monitors_wraps_capture_errors(monkeypatch):
    class BrokenCapture:
        def __enter__(self):
            raise OSError("private machine details")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(mm, "_require_windows", lambda: None)
    monkeypatch.setattr(mm, "_load_mss", lambda: SimpleNamespace(mss=BrokenCapture))
    with pytest.raises(mm.MultiMonitorError, match="monitor information is unavailable") as exc:
        mm.list_monitors()
    assert "private machine details" not in str(exc.value)


def test_physical_dpi_context_restores_context_and_tolerates_unavailable_api(monkeypatch):
    calls = []

    class User32:
        def SetThreadDpiAwarenessContext(self, value):
            calls.append(value)
            return "previous"

    monkeypatch.setattr(mm, "_windows_user32", lambda: User32())
    with mm._physical_dpi_context():
        calls.append("body")
    assert calls[0].value == ctypes.c_void_p(-4).value
    assert calls[1:] == ["body", "previous"]

    monkeypatch.setattr(
        mm, "_windows_user32",
        lambda: (_ for _ in ()).throw(mm.MultiMonitorError("unsupported")),
    )
    with mm._physical_dpi_context():
        calls.append("fallback body")
    assert calls[-1] == "fallback body"


def test_enum_windows_filters_hidden_empty_protected_and_invalid_windows(monkeypatch):
    windows = {
        1: _window(hwnd=1, title="Hidden"),
        2: _window(hwnd=2, title=""),
        3: _window(hwnd=3, pid=10, title="System"),
        4: _window(hwnd=4, title="Zero bounds", width=0),
        5: _window(hwnd=5, title="Visible"),
    }

    class Gui:
        def IsWindowVisible(self, hwnd):
            return hwnd != 1

        def GetWindowText(self, hwnd):
            return windows[hwnd]["title"]

        def GetWindowRect(self, hwnd):
            win = windows[hwnd]
            return win["left"], win["top"], win["left"] + win["width"], win["top"] + win["height"]

        def EnumWindows(self, callback, extra):
            for hwnd in windows:
                callback(hwnd, extra)

    monkeypatch.setattr(mm, "_load_win32gui", lambda: Gui())
    monkeypatch.setattr(mm, "_physical_dpi_context", nullcontext)
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_is_protected_process", lambda pid: pid < 100)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, windows[hwnd]["pid"]),
    ))

    result = mm._enum_windows()

    assert [window["hwnd"] for window in result] == [5]
    assert result[0]["process_name"] == "notepad.exe"


def test_enum_windows_skips_transient_failures_and_wraps_enumeration_error(monkeypatch):
    class Gui:
        def IsWindowVisible(self, _hwnd):
            raise OSError("private")

        def EnumWindows(self, callback, extra):
            callback(1, extra)

    monkeypatch.setattr(mm, "_load_win32gui", lambda: Gui())
    monkeypatch.setattr(mm, "_physical_dpi_context", nullcontext)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace())
    assert mm._enum_windows() == []

    def fail(_callback, _extra):
        raise OSError("private title")

    monkeypatch.setattr(mm, "_load_win32gui", lambda: SimpleNamespace(EnumWindows=fail))
    with pytest.raises(mm.MultiMonitorError, match="could not enumerate") as exc:
        mm._enum_windows()
    assert "private title" not in str(exc.value)


def test_foreground_window_errors_and_success_are_sanitized(monkeypatch):
    from ctypes import wintypes

    class User32:
        hwnd = 42
        pid = 1234

        def GetForegroundWindow(self):
            return self.hwnd

        def GetWindowThreadProcessId(self, _hwnd, pid_pointer):
            ctypes.cast(pid_pointer, ctypes.POINTER(wintypes.DWORD)).contents.value = self.pid

    user32 = User32()
    monkeypatch.setattr(mm, "_windows_user32", lambda: user32)
    assert mm._foreground_window() == (42, 1234)
    user32.hwnd = 0
    with pytest.raises(mm.MultiMonitorError, match="no foreground window"):
        mm._foreground_window()
    user32.hwnd, user32.pid = 42, 0
    with pytest.raises(mm.MultiMonitorError, match="could not be verified"):
        mm._foreground_window()


def test_rect_and_place_window_use_safe_flags_and_report_os_failures(monkeypatch):
    from ctypes import wintypes

    class User32:
        succeeds = True
        placement = None

        def GetWindowRect(self, _hwnd, pointer):
            if self.succeeds:
                rect = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
                rect.left, rect.top, rect.right, rect.bottom = 1, 2, 31, 42
            return self.succeeds

        def SetWindowPos(self, *args):
            self.placement = args
            return self.succeeds

    user32 = User32()
    monkeypatch.setattr(mm, "_windows_user32", lambda: user32)
    monkeypatch.setattr(mm, "_physical_dpi_context", nullcontext)
    assert mm._rect_for_window(9) == (1, 2, 31, 42)
    mm._place_window(9, 10, 20, 30, 40)
    assert user32.placement == (9, None, 10, 20, 30, 40, 0x14)
    user32.succeeds = False
    with pytest.raises(mm.MultiMonitorError, match="position is unavailable"):
        mm._rect_for_window(9)
    with pytest.raises(mm.MultiMonitorError, match="could not arrange"):
        mm._place_window(9, 0, 0, 10, 10)


@pytest.mark.parametrize("index", [True, -1, 2, "0"])
def test_monitor_index_validation(index):
    with pytest.raises(mm.MultiMonitorError, match="monitor_index"):
        mm._check_monitor_index(index, [_MONITOR_A])


def test_move_foreground_window_moves_only_eligible_verified_process(monkeypatch):
    placements = []
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_foreground_window", lambda: (80, 500))
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_rect_for_window", lambda _hwnd: (0, 0, 400, 200))
    monkeypatch.setattr(mm, "_place_window", lambda *args: placements.append(args))

    assert mm.move_foreground_window(0) == {"ok": True, "monitor_index": 0}
    assert placements == [(80, 760, 440, 400, 200)]

    monkeypatch.setattr(mm, "_process_name", lambda _pid: "services.exe")
    with pytest.raises(mm.MultiMonitorError, match="protected processes"):
        mm.move_foreground_window(0)


def test_active_monitor_rejects_protected_window_and_falls_back_to_nearest(monkeypatch):
    monkeypatch.setattr(mm, "_foreground_window", lambda: (90, 500))
    monkeypatch.setattr(mm, "_is_protected_process", lambda _pid: False)
    monkeypatch.setattr(mm, "_rect_for_window", lambda _hwnd: (3000, 1500, 3100, 1600))
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A, _MONITOR_B])
    assert mm.get_active_monitor() == _MONITOR_A

    monkeypatch.setattr(mm, "_is_protected_process", lambda _pid: True)
    with pytest.raises(mm.MultiMonitorError, match="not an eligible"):
        mm.get_active_monitor()


def test_window_monitor_falls_back_to_primary_and_arrange_empty_uses_active(monkeypatch):
    assert mm._window_monitor_index(_window(left=3000, top=3000), [_MONITOR_A, _MONITOR_B]) == 0
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "get_active_monitor", lambda: _MONITOR_A)
    monkeypatch.setattr(mm, "_enum_windows", lambda: [])
    assert mm.arrange_windows("grid") == {
        "ok": True, "layout": "grid", "monitor_index": 0, "arranged": 0,
    }
    with pytest.raises(mm.MultiMonitorError, match="grid.*cascade"):
        mm.arrange_windows("invalid", 0)


@pytest.mark.parametrize("layout", ["grid", "cascade", "left-right"])
def test_arrange_uses_active_monitor_and_bounds_small_displays(monkeypatch, layout):
    tiny_monitor = {**_MONITOR_A, "width": 2, "height": 2}
    placements = []
    monkeypatch.setattr(mm, "list_monitors", lambda: [tiny_monitor])
    monkeypatch.setattr(mm, "get_active_monitor", lambda: tiny_monitor)
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window(), _window(hwnd=102)])
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_place_window", lambda *args: placements.append(args))
    result = mm.arrange_windows(layout)
    assert result["arranged"] == 2
    assert all(call[3] >= 1 and call[4] >= 1 for call in placements)


def test_save_layout_handles_corrupt_old_data_empty_windows_and_write_failure(monkeypatch, tmp_path):
    path = tmp_path / "layout.json"
    path.write_text("invalid json", encoding="utf-8")
    monkeypatch.setattr(mm, "_layout_path", lambda: path)
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [])
    assert mm.save_layout() == {"ok": True, "saved": 0}
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == mm.LAYOUT_VERSION

    with pytest.raises(mm.MultiMonitorError, match="layout_name"):
        mm.save_layout(" ")

    monkeypatch.setattr(mm, "_layout_path", lambda: tmp_path)
    with pytest.raises(mm.MultiMonitorError, match="could not be saved"):
        mm.save_layout()


@pytest.mark.parametrize(
    "payload",
    [
        {"version": -1, "layouts": {}},
        {"version": mm.LAYOUT_VERSION, "layouts": {mm._digest("default"): [{"bad": True}]}},
    ],
)
def test_restore_layout_skips_invalid_records_and_unmatched_windows(monkeypatch, tmp_path, payload):
    path = tmp_path / "layout.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(mm, "_layout_path", lambda: path)
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window()])
    monkeypatch.setattr(mm, "_place_window", lambda *_args: pytest.fail("Invalid layout placed window"))
    if payload["version"] != mm.LAYOUT_VERSION:
        with pytest.raises(mm.MultiMonitorError, match="unavailable"):
            mm.restore_layout()
    else:
        assert mm.restore_layout() == {"ok": True, "restored": 0}


def test_restore_layout_rejects_invalid_record_for_matching_window(monkeypatch, tmp_path):
    path = tmp_path / "layout.json"
    record = {
        "title_hash": mm._digest("private title"),
        "process_hash": mm._digest("notepad.exe"),
        "monitor_index": 99,
        "width_fraction": 0.5,
        "height_fraction": 0.5,
        "left_fraction": 0,
        "top_fraction": 0,
    }
    path.write_text(json.dumps({
        "version": mm.LAYOUT_VERSION,
        "layouts": {mm._digest("default"): [record]},
    }), encoding="utf-8")
    monkeypatch.setattr(mm, "_layout_path", lambda: path)
    monkeypatch.setattr(mm, "list_monitors", lambda: [_MONITOR_A])
    monkeypatch.setattr(mm, "_enum_windows", lambda: [_window()])
    monkeypatch.setattr(mm, "_process_name", lambda _pid: "notepad.exe")
    monkeypatch.setattr(mm, "_place_window", lambda *_args: pytest.fail("Invalid index placed window"))
    assert mm.restore_layout() == {"ok": True, "restored": 0}


def test_manager_unavailable_snapshots_and_restart_after_stop():
    manager = mm.MultiMonitorManager(
        poll_interval=60,
        monitor_provider=lambda: [],
        active_monitor_provider=lambda: pytest.fail("No monitor should request active display"),
    )
    initial = manager.snapshot()
    assert initial["error"] == "not_started"
    first = manager.start()
    assert first["available"] is False
    assert first["change_counter"] == 0
    assert manager.stop(timeout=1) is True
    with pytest.raises(ValueError, match="non-negative"):
        manager.stop(timeout=-1)
    assert manager.start()["change_counter"] == 0
    assert manager.stop(timeout=1) is True


def test_manager_active_provider_failure_changes_error_without_leaking(monkeypatch):
    manager = mm.MultiMonitorManager(
        poll_interval=60,
        monitor_provider=lambda: [dict(_MONITOR_A, title="private title")],
        active_monitor_provider=lambda: (_ for _ in ()).throw(
            RuntimeError("C:/private/title")
        ),
    )
    snapshot = manager.start()
    try:
        assert snapshot["available"] is True
        assert snapshot["active_monitor"] is None
        assert snapshot["error"] == "Active monitor information is unavailable."
        assert "private" not in str(snapshot)
    finally:
        assert manager.stop(timeout=1) is True


def test_manager_change_counter_ignores_active_window_switch():
    state = {"active": _MONITOR_A}
    manager = mm.MultiMonitorManager(
        poll_interval=60,
        monitor_provider=lambda: [_MONITOR_A],
        active_monitor_provider=lambda: state["active"],
    )
    initial = manager.start()
    state["active"] = _MONITOR_B
    manager._refresh()
    try:
        snapshot = manager.snapshot()
        assert snapshot["active_monitor"]["index"] == 1
        assert snapshot["change_counter"] == initial["change_counter"]
    finally:
        assert manager.stop(timeout=1) is True


def test_manager_snapshot_is_detached_and_stop_before_start_succeeds():
    manager = mm.MultiMonitorManager()
    assert manager.stop(timeout=0) is True
    snapshot = manager.snapshot()
    snapshot["monitors"].append({"title": "private"})
    snapshot["active_monitor"] = {"path": "private"}
    assert manager.snapshot()["monitors"] == []
    assert manager.snapshot()["active_monitor"] is None

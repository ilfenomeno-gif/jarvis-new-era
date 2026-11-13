"""Windows monitor geometry, guarded window placement, and local layouts."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import sys
import threading
from collections.abc import Callable
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

POLL_INTERVAL_SECONDS = 3.0
LAYOUT_VERSION = 1
_PROTECTED_PROCESS_NAMES = frozenset({
    "system",
    "system idle process",
    "registry",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
    "winlogon.exe",
    "fontdrvhost.exe",
    "dwm.exe",
    "spoolsv.exe",
    "sihost.exe",
    "explorer.exe",
    "taskhostw.exe",
    "runtimebroker.exe",
    "securityhealthservice.exe",
    "audiodg.exe",
    "trustedinstaller.exe",
    "wuauclt.exe",
    "wudfhost.exe",
    "msmpeng.exe",
    "searchindexer.exe",
    "searchhost.exe",
})


class MultiMonitorError(RuntimeError):
    """A safe, user-facing multi-monitor operation failure."""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise MultiMonitorError("Multi-monitor control is available only on Windows.")


def _load_mss() -> Any:
    try:
        import mss
    except Exception as exc:
        raise MultiMonitorError(
            "Multi-monitor discovery is unavailable because the optional mss package is missing."
        ) from exc
    return mss


def _windows_user32() -> Any:
    _require_windows()
    try:
        user32 = ctypes.windll.user32
    except (AttributeError, OSError) as exc:
        raise MultiMonitorError("Windows display control is unavailable.") from exc
    try:
        from ctypes import wintypes

        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = (
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        )
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = (
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        )
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.SetThreadDpiAwarenessContext.argtypes = (wintypes.HANDLE,)
        user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
    except (AttributeError, TypeError):
        pass
    return user32


@contextmanager
def _physical_dpi_context():
    """Use per-monitor-v2 coordinates for window APIs when Windows supports it."""
    try:
        user32 = _windows_user32()
        setter = user32.SetThreadDpiAwarenessContext
        previous = setter(ctypes.c_void_p(-4))  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except Exception:
        yield
        return
    try:
        yield
    finally:
        with suppress(Exception):
            setter(previous)


def _load_psutil() -> Any:
    try:
        import psutil
    except Exception as exc:
        raise MultiMonitorError(
            "Window operations are unavailable because the optional psutil package is missing."
        ) from exc
    return psutil


def _process_name(pid: int) -> str:
    psutil = _load_psutil()
    try:
        return psutil.Process(pid).name().casefold()
    except Exception as exc:
        raise MultiMonitorError("The window process could not be verified.") from exc


def _is_protected_process(pid: int, process_name: str | None = None) -> bool:
    if pid < 100:
        return True
    try:
        name = process_name if process_name is not None else _process_name(pid)
    except MultiMonitorError:
        # Fail closed: an unverified process must never be moved.
        return True
    return name.casefold() in _PROTECTED_PROCESS_NAMES


def _monitor_dpi(left: int, top: int, width: int, height: int) -> tuple[int | None, int | None]:
    try:
        from ctypes import wintypes

        user32 = _windows_user32()
        point = wintypes.POINT(left + width // 2, top + height // 2)
        with _physical_dpi_context():
            handle = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
        shcore = ctypes.windll.shcore
        x_dpi, y_dpi = wintypes.UINT(), wintypes.UINT()
        status = shcore.GetDpiForMonitor(handle, 0, ctypes.byref(x_dpi), ctypes.byref(y_dpi))
        if status == 0:
            return int(x_dpi.value), int(y_dpi.value)
    except Exception:
        pass
    return None, None


def list_monitors() -> list[dict[str, int | bool | None]]:
    """Return physical desktop geometry and effective DPI, without window metadata."""
    _require_windows()
    mss = _load_mss()
    try:
        with mss.mss() as session:
            # MSS index 0 is the virtual bounding rectangle, not a physical display.
            raw_monitors = list(session.monitors[1:])
    except Exception as exc:
        raise MultiMonitorError("Windows monitor information is unavailable.") from exc
    if not raw_monitors:
        raise MultiMonitorError("No physical displays are available.")

    monitors: list[dict[str, int | bool | None]] = []
    for index, monitor in enumerate(raw_monitors):
        try:
            left, top = int(monitor["left"]), int(monitor["top"])
            width, height = int(monitor["width"]), int(monitor["height"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MultiMonitorError("Windows returned invalid monitor information.") from exc
        if width <= 0 or height <= 0:
            raise MultiMonitorError("Windows returned invalid monitor dimensions.")
        dpi_x, dpi_y = _monitor_dpi(left, top, width, height)
        monitors.append({
            "index": index,
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}",
            "dpi_x": dpi_x,
            "dpi_y": dpi_y,
            "primary": index == 0,
        })
    return monitors


def _load_win32gui() -> Any:
    _require_windows()
    try:
        import win32gui
    except Exception as exc:
        raise MultiMonitorError(
            "Window operations are unavailable because the optional pywin32 package is missing."
        ) from exc
    return win32gui


def _enum_windows() -> list[dict[str, Any]]:
    win32gui = _load_win32gui()
    try:
        import win32process
    except Exception as exc:
        raise MultiMonitorError(
            "Window operations are unavailable because the optional pywin32 package is missing."
        ) from exc

    windows: list[dict[str, Any]] = []

    def collect(hwnd: int, _extra: Any) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
            if _is_protected_process(int(pid)):
                return True
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right <= left or bottom <= top:
                return True
            windows.append({
                "hwnd": int(hwnd),
                "pid": int(pid),
                "title": title,
                "process_name": _process_name(int(pid)),
                "left": int(left),
                "top": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
            })
        except Exception:
            # Ignore inaccessible or transient windows without leaking details.
            return True
        return True

    try:
        with _physical_dpi_context():
            win32gui.EnumWindows(collect, None)
    except Exception as exc:
        raise MultiMonitorError("Windows could not enumerate eligible windows.") from exc
    return windows


def _foreground_window() -> tuple[int, int]:
    user32 = _windows_user32()
    try:
        from ctypes import wintypes

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            raise MultiMonitorError("There is no foreground window to move.")
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            raise MultiMonitorError("The foreground process could not be verified.")
        return int(hwnd), int(pid.value)
    except MultiMonitorError:
        raise
    except Exception as exc:
        raise MultiMonitorError("The foreground window could not be inspected.") from exc


def _rect_for_window(hwnd: int) -> tuple[int, int, int, int]:
    from ctypes import wintypes

    rect = wintypes.RECT()
    with _physical_dpi_context():
        if not _windows_user32().GetWindowRect(hwnd, ctypes.byref(rect)):
            raise MultiMonitorError("The window position is unavailable.")
    return rect.left, rect.top, rect.right, rect.bottom


def _place_window(hwnd: int, left: int, top: int, width: int, height: int) -> None:
    flags = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
    with _physical_dpi_context():
        if not _windows_user32().SetWindowPos(hwnd, None, left, top, width, height, flags):
            raise MultiMonitorError("Windows could not arrange the selected window.")


def _place_safe_window(window: dict[str, Any], left: int, top: int, width: int, height: int) -> None:
    if _is_protected_process(int(window["pid"])):
        raise MultiMonitorError("Moving system and protected processes is not allowed.")
    _place_window(int(window["hwnd"]), left, top, width, height)


def _centered_position(
    window: dict[str, Any], monitor: dict[str, Any]
) -> tuple[int, int, int, int]:
    width = min(int(window["width"]), int(monitor["width"]))
    height = min(int(window["height"]), int(monitor["height"]))
    left = int(monitor["left"]) + max(0, (int(monitor["width"]) - width) // 2)
    top = int(monitor["top"]) + max(0, (int(monitor["height"]) - height) // 2)
    return left, top, width, height


def _check_monitor_index(monitor_index: int, monitors: list[dict[str, Any]]) -> dict[str, Any]:
    if isinstance(monitor_index, bool) or not isinstance(monitor_index, int):
        raise MultiMonitorError("monitor_index must be an integer.")
    if not 0 <= monitor_index < len(monitors):
        raise MultiMonitorError("monitor_index does not identify an available display.")
    return monitors[monitor_index]


def move_window_to_monitor(window_title: str, monitor_index: int) -> dict[str, int | bool]:
    """Move one exact-title match; never return the title or process identity."""
    if not isinstance(window_title, str) or not window_title.strip():
        raise MultiMonitorError("window_title must be non-empty.")
    monitors = list_monitors()
    monitor = _check_monitor_index(monitor_index, monitors)
    candidates = [
        window for window in _enum_windows()
        if window["title"].casefold() == window_title.strip().casefold()
    ]
    if not candidates:
        raise MultiMonitorError("No eligible window matched the requested title.")
    if len(candidates) != 1:
        raise MultiMonitorError("The requested title matches multiple windows.")
    window = candidates[0]
    position = _centered_position(window, monitor)
    _place_safe_window(window, *position)
    return {"ok": True, "monitor_index": monitor_index}


def move_foreground_window(monitor_index: int) -> dict[str, int | bool]:
    """Compatibility API: move the safe foreground window to a display."""
    monitors = list_monitors()
    monitor = _check_monitor_index(monitor_index, monitors)
    hwnd, pid = _foreground_window()
    if _is_protected_process(pid):
        raise MultiMonitorError("Moving system and protected processes is not allowed.")
    left, top, right, bottom = _rect_for_window(hwnd)
    position = _centered_position(
        {"width": right - left, "height": bottom - top},
        monitor,
    )
    _place_window(hwnd, *position)
    return {"ok": True, "monitor_index": monitor_index}


def swap_active_window(layout: str = "swap") -> dict[str, int | bool]:
    """Swap Jarvis with the active eligible window, or place both side by side."""
    if layout not in {"swap", "jarvis_left", "jarvis_right"}:
        raise MultiMonitorError("Layout must be swap, jarvis_left, or jarvis_right.")
    windows = _enum_windows()
    hwnd, pid = _foreground_window()
    own = [window for window in windows if window["pid"] == os.getpid()]
    if len(own) > 1:
        own = [window for window in own if "jarvis" in window.get("title", "").casefold()]
    if len(own) != 1:
        raise MultiMonitorError("Impossibile identificare un'unica finestra Jarvis.")
    jarvis = own[0]
    gui = _load_win32gui()
    try:
        import pywintypes
        import win32process
    except ImportError as exc:
        raise MultiMonitorError("Impossibile verificare o spostare le finestre.") from exc
    if hwnd == jarvis["hwnd"]:
        try:
            others = [window for window in windows if window["pid"] != os.getpid()
                      and not gui.IsIconic(window["hwnd"])]
        except pywintypes.error as exc:
            raise MultiMonitorError("Impossibile verificare le finestre disponibili.") from exc
        if not others:
            raise MultiMonitorError("Nessun'altra finestra idonea da scambiare.")
        other = max(others, key=lambda window: window["width"] * window["height"])
    else:
        matches = [window for window in windows if window["hwnd"] == hwnd and window["pid"] == pid]
        if len(matches) != 1 or pid == os.getpid():
            raise MultiMonitorError("La finestra attiva non è idonea allo scambio.")
        other = matches[0]
    try:
        def place_verified(window, position):
            handle = window["hwnd"]
            try:
                eligible = (gui.IsWindow(handle) and not gui.IsIconic(handle)
                            and win32process.GetWindowThreadProcessId(handle)[1] == window["pid"]
                            and not _is_protected_process(window["pid"]))
            except pywintypes.error as exc:
                raise MultiMonitorError("Impossibile verificare la finestra selezionata.") from exc
            if not eligible:
                raise MultiMonitorError("Una finestra non è verificabile o è minimizzata.")
            if gui.IsZoomed(handle):
                placement = gui.GetWindowPlacement(handle)
                gui.ShowWindow(handle, 9)  # SW_RESTORE
                try:
                    _place_safe_window(window, *position)
                except (MultiMonitorError, OSError, pywintypes.error):
                    gui.SetWindowPlacement(handle, placement)
                    raise
                return placement
            _place_safe_window(window, *position)
            return None

        original = [tuple(window[key] for key in ("left", "top", "width", "height"))
                    for window in (jarvis, other)]
        if layout == "swap":
            positions = [original[1], original[0]]
        else:
            monitors = list_monitors()
            monitor = monitors[_window_monitor_index(other, monitors)]
            left, top = int(monitor["left"]), int(monitor["top"])
            width, height = int(monitor["width"]), int(monitor["height"])
            first_width = width // 2
            left_rect = (left, top, first_width, height)
            right_rect = (left + first_width, top, width - first_width, height)
            positions = [left_rect, right_rect] if layout == "jarvis_left" else [right_rect, left_rect]
        jarvis_placement = place_verified(jarvis, positions[0])
        try:
            place_verified(other, positions[1])
        except (MultiMonitorError, OSError, pywintypes.error) as exc:
            try:
                place_verified(jarvis, original[0])
                if jarvis_placement is not None:
                    gui.SetWindowPlacement(jarvis["hwnd"], jarvis_placement)
            except (MultiMonitorError, OSError, pywintypes.error) as rollback_error:
                raise MultiMonitorError("Scambio incompleto; ripristino della finestra Jarvis fallito.") from rollback_error
            raise MultiMonitorError("Scambio non riuscito; posizione Jarvis ripristinata.") from exc
    except MultiMonitorError:
        raise
    except (OSError, ValueError, pywintypes.error) as exc:
        raise MultiMonitorError("Impossibile verificare o spostare le finestre.") from exc
    return {"ok": True}


def get_active_monitor() -> dict[str, Any]:
    """Identify the display with the largest intersection with the foreground window."""
    hwnd, pid = _foreground_window()
    if _is_protected_process(pid):
        raise MultiMonitorError("The foreground window is not an eligible user window.")
    left, top, right, bottom = _rect_for_window(hwnd)
    center_x, center_y = (left + right) // 2, (top + bottom) // 2
    monitors = list_monitors()
    matching = [
        monitor for monitor in monitors
        if int(monitor["left"]) <= center_x < int(monitor["left"]) + int(monitor["width"])
        and int(monitor["top"]) <= center_y < int(monitor["top"]) + int(monitor["height"])
    ]
    if matching:
        return matching[0]
    return min(
        monitors,
        key=lambda monitor: (
            (center_x - (int(monitor["left"]) + int(monitor["width"]) // 2)) ** 2
            + (center_y - (int(monitor["top"]) + int(monitor["height"]) // 2)) ** 2
        ),
    )


def _window_monitor_index(window: dict[str, Any], monitors: list[dict[str, Any]]) -> int:
    center_x = int(window["left"]) + int(window["width"]) // 2
    center_y = int(window["top"]) + int(window["height"]) // 2
    for monitor in monitors:
        if (
            int(monitor["left"]) <= center_x < int(monitor["left"]) + int(monitor["width"])
            and int(monitor["top"]) <= center_y < int(monitor["top"]) + int(monitor["height"])
        ):
            return int(monitor["index"])
    return 0


def arrange_windows(layout: str, monitor_index: int | None = None) -> dict[str, int | str | bool]:
    """Arrange eligible visible windows as grid, cascade, or left-right."""
    if layout not in {"grid", "cascade", "left-right"}:
        raise MultiMonitorError("layout must be 'grid', 'cascade', or 'left-right'.")
    monitors = list_monitors()
    monitor = (
        _check_monitor_index(monitor_index, monitors)
        if monitor_index is not None
        else get_active_monitor()
    )
    windows = [
        window for window in _enum_windows()
        if _window_monitor_index(window, monitors) == monitor["index"]
    ]
    if not windows:
        return {"ok": True, "layout": layout, "monitor_index": monitor["index"], "arranged": 0}
    bounds = (
        int(monitor["left"]), int(monitor["top"]),
        int(monitor["width"]), int(monitor["height"]),
    )
    left, top, width, height = bounds
    if layout == "grid":
        columns = max(1, int(len(windows) ** 0.5))
        rows = (len(windows) + columns - 1) // columns
        for index, window in enumerate(windows):
            column, row = index % columns, index // columns
            cell_left = left + column * width // columns
            cell_top = top + row * height // rows
            cell_right = left + (column + 1) * width // columns
            cell_bottom = top + (row + 1) * height // rows
            _place_safe_window(
                window, cell_left, cell_top, cell_right-cell_left, cell_bottom-cell_top
            )
    elif layout == "left-right":
        for index, window in enumerate(windows):
            cell_left = left + index * width // len(windows)
            cell_right = left + (index + 1) * width // len(windows)
            _place_safe_window(window, cell_left, top, cell_right - cell_left, height)
    else:
        offset = 32
        window_width = max(1, width * 3 // 4)
        window_height = max(1, height * 3 // 4)
        for index, window in enumerate(windows):
            cascade_left = left + (index * offset) % max(1, width - window_width + 1)
            cascade_top = top + (index * offset) % max(1, height - window_height + 1)
            _place_safe_window(
                window, cascade_left, cascade_top, window_width, window_height
            )
    return {"ok": True, "layout": layout, "monitor_index": monitor["index"], "arranged": len(windows)}


def _layout_path() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    base = Path(root) if root else Path.home() / "AppData" / "Local"
    return base / "JarvisVII" / "monitor_layouts.json"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def save_layout(layout_name: str = "default") -> dict[str, int | bool]:
    """Save window identities as one-way hashes and geometry in local app data."""
    if not isinstance(layout_name, str) or not layout_name.strip():
        raise MultiMonitorError("layout_name must be non-empty.")
    monitors = list_monitors()
    windows = _enum_windows()
    saved = []
    for window in windows:
        monitor = monitors[_window_monitor_index(window, monitors)]
        saved.append({
            "title_hash": _digest(window["title"].casefold()),
            "process_hash": _digest(window["process_name"]),
            "left_fraction": (window["left"] - int(monitor["left"])) / int(monitor["width"]),
            "top_fraction": (window["top"] - int(monitor["top"])) / int(monitor["height"]),
            "width_fraction": window["width"] / int(monitor["width"]),
            "height_fraction": window["height"] / int(monitor["height"]),
            "monitor_index": _window_monitor_index(window, monitors),
        })
    path = _layout_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != LAYOUT_VERSION:
                data = {"version": LAYOUT_VERSION, "layouts": {}}
        except FileNotFoundError:
            data = {"version": LAYOUT_VERSION, "layouts": {}}
        except (OSError, ValueError):
            data = {"version": LAYOUT_VERSION, "layouts": {}}
        layouts = data.setdefault("layouts", {})
        layouts[_digest(layout_name.strip().casefold())] = saved
        temporary = path.with_suffix(".json.new")
        temporary.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
    except Exception as exc:
        raise MultiMonitorError("The local window layout could not be saved.") from exc
    return {"ok": True, "saved": len(saved)}


def restore_layout(layout_name: str = "default") -> dict[str, int | bool]:
    """Restore a named layout by matching one-way title/process hashes locally."""
    if not isinstance(layout_name, str) or not layout_name.strip():
        raise MultiMonitorError("layout_name must be non-empty.")
    path = _layout_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data["layouts"][_digest(layout_name.strip().casefold())]
    except FileNotFoundError as exc:
        raise MultiMonitorError("No saved layout is available.") from exc
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise MultiMonitorError("The requested saved layout is unavailable.") from exc

    monitors = list_monitors()
    current = _enum_windows()
    available = {}
    for window in current:
        key = (_digest(window["title"].casefold()), _digest(window["process_name"]))
        available.setdefault(key, []).append(window)
    restored = 0
    for record in records:
        key = (record.get("title_hash"), record.get("process_hash"))
        matches = available.get(key, [])
        if not matches:
            continue
        window = matches.pop(0)
        if _is_protected_process(window["pid"]):
            continue
        monitor_index = record.get("monitor_index")
        try:
            monitor = _check_monitor_index(monitor_index, monitors)
            width = max(1, min(round(record["width_fraction"] * int(monitor["width"])),
                               int(monitor["width"])))
            height = max(1, min(round(record["height_fraction"] * int(monitor["height"])),
                                int(monitor["height"])))
            left = int(monitor["left"]) + min(
                max(0, round(record["left_fraction"] * int(monitor["width"]))),
                int(monitor["width"]) - width,
            )
            top = int(monitor["top"]) + min(
                max(0, round(record["top_fraction"] * int(monitor["height"]))),
                int(monitor["height"]) - height,
            )
            _place_window(
                window["hwnd"],
                left,
                top,
                width,
                height,
            )
        except (KeyError, TypeError, ValueError, MultiMonitorError):
            continue
        restored += 1
    return {"ok": True, "restored": restored}


class MultiMonitorManager:
    """Poll displays and active monitor; snapshots contain no window identifiers."""

    def __init__(
        self,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        monitor_provider: Callable[[], list[dict[str, Any]]] = list_monitors,
        active_monitor_provider: Callable[[], dict[str, Any]] = get_active_monitor,
    ) -> None:
        if poll_interval <= 0:
            raise ValueError("poll_interval must be greater than zero.")
        self._poll_interval = float(poll_interval)
        self._monitor_provider = monitor_provider
        self._active_monitor_provider = active_monitor_provider
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: dict[str, Any] = {
            "available": False,
            "monitors": [],
            "active_monitor": None,
            "change_counter": 0,
            "error": "not_started",
        }

    def start(self) -> dict[str, Any]:
        """Refresh immediately and start background polling; safe to call repeatedly."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._copy_snapshot()
            self._stop_event.clear()
            self._refresh()
            self._thread = threading.Thread(
                target=self._poll, name="multi-monitor-poll", daemon=True
            )
            self._thread.start()
            return self._copy_snapshot()

    def stop(self, timeout: float = 1.0) -> bool:
        """Stop polling, returning False if the worker has not exited by timeout."""
        if timeout < 0:
            raise ValueError("timeout must be non-negative.")
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._lock:
            stopped = thread is None or not thread.is_alive()
            if stopped:
                self._thread = None
            return stopped

    def snapshot(self) -> dict[str, Any]:
        """Return {available, monitors, active_monitor, change_counter, error}."""
        with self._lock:
            return self._copy_snapshot()

    def _copy_snapshot(self) -> dict[str, Any]:
        value = self._snapshot
        return {
            "available": value["available"],
            "monitors": [dict(monitor) for monitor in value["monitors"]],
            "active_monitor": dict(value["active_monitor"]) if value["active_monitor"] else None,
            "change_counter": value["change_counter"],
            "error": value["error"],
        }

    def _refresh(self) -> None:
        try:
            monitors = self._monitor_provider()
            safe_monitors = [
                {key: monitor.get(key) for key in (
                    "index", "left", "top", "width", "height", "resolution",
                    "dpi_x", "dpi_y", "primary",
                )}
                for monitor in monitors
            ]
            available, error = bool(safe_monitors), None
            if not available:
                error = "No physical displays are available."
        except Exception:
            safe_monitors, safe_active = [], None
            available, error = False, "Monitor information is unavailable."
        if not available:
            safe_active = None
        if available:
            try:
                active = self._active_monitor_provider()
                safe_active = {key: active.get(key) for key in (
                    "index", "left", "top", "width", "height", "resolution",
                    "dpi_x", "dpi_y", "primary",
                )}
            except Exception:
                safe_active = None
                error = "Active monitor information is unavailable."
        with self._lock:
            changed = (
                safe_monitors != self._snapshot["monitors"]
                or available != self._snapshot["available"]
            )
            self._snapshot = {
                "available": available,
                "monitors": safe_monitors,
                "active_monitor": safe_active,
                "change_counter": self._snapshot["change_counter"] + int(changed),
                "error": error,
            }

    def _poll(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            self._refresh()

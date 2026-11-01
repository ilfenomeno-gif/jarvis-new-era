"""Local screen perception and guarded desktop input primitives."""
from __future__ import annotations

import ctypes
import math
import ntpath
import os
import platform
import threading
import time
from datetime import datetime, timezone
from typing import Any


INPUT_ALLOWLIST_ENV = "JARVIS_INPUT_ALLOWLIST"
DEFAULT_ALLOWED_PROCESSES = frozenset({
    "notepad.exe",
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "code.exe",
})
EMERGENCY_STOP_HOTKEY = "ctrl+alt+esc"
MAX_UIA_CONTROLS = 300
MAX_OCR_WORDS = 300
_emergency_stop = threading.Event()
_emergency_hook_lock = threading.Lock()
_emergency_hook = None
_keyboard_module = None


def _require_windows() -> None:
    if platform.system() != "Windows":
        raise RuntimeError("Computer Use input and UI Automation require Windows.")


def allowed_processes(environ: dict[str, str] | None = None) -> frozenset[str]:
    values = os.environ if environ is None else environ
    raw = values.get(INPUT_ALLOWLIST_ENV)
    if raw is None:
        return DEFAULT_ALLOWED_PROCESSES
    return frozenset(
        name
        for item in raw.split(",")
        if (name := ntpath.basename(item.strip()).casefold())
    )


def foreground_process() -> tuple[int, str]:
    _require_windows()
    import psutil
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        raise RuntimeError("Could not identify the foreground window.")
    process_id = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        raise RuntimeError("Could not identify the foreground process.")
    try:
        process_name = psutil.Process(process_id.value).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        raise RuntimeError("Could not inspect the foreground process.") from exc
    return int(hwnd), process_name.casefold()


def require_allowed_foreground() -> tuple[int, str]:
    hwnd, process_name = foreground_process()
    if process_name not in allowed_processes():
        allowed = ", ".join(sorted(allowed_processes())) or "(none)"
        raise PermissionError(
            f"Input blocked for {process_name}; allowed processes: {allowed}."
        )
    return hwnd, process_name


def arm_emergency_stop(keyboard_module: Any = None) -> None:
    """Install the global stop hotkey once; failure prevents desktop input."""
    global _emergency_hook, _keyboard_module
    _require_windows()
    with _emergency_hook_lock:
        if _emergency_hook is not None:
            return
        keyboard = keyboard_module
        if keyboard is None:
            import keyboard

        try:
            _emergency_hook = keyboard.add_hotkey(
                EMERGENCY_STOP_HOTKEY, _emergency_stop.set
            )
            _keyboard_module = keyboard
        except Exception as exc:
            raise RuntimeError(
                f"Could not install emergency stop hotkey "
                f"({EMERGENCY_STOP_HOTKEY}): {exc}"
            ) from exc


def stop_emergency_stop() -> None:
    global _emergency_hook, _keyboard_module
    with _emergency_hook_lock:
        if _emergency_hook is None:
            return
        hook, keyboard = _emergency_hook, _keyboard_module
        _emergency_hook = None
        _keyboard_module = None
        try:
            keyboard.remove_hotkey(hook)
        except Exception as exc:
            raise RuntimeError("Could not remove the emergency stop hotkey.") from exc


def emergency_stop_triggered() -> bool:
    return _emergency_stop.is_set()


def _check_emergency_stop() -> None:
    if emergency_stop_triggered():
        raise RuntimeError(
            "Computer input stopped by Ctrl+Alt+Esc. Restart Jarvis to re-enable it."
        )


def _assert_same_foreground(hwnd: int, process_name: str | None = None) -> None:
    current_hwnd, current_process = require_allowed_foreground()
    if current_hwnd != hwnd or (
        process_name is not None and current_process != process_name
    ):
        raise PermissionError(
            "The foreground window changed; no further input was sent."
        )


def _assert_same_foreground_with_retry(
    hwnd: int, process_name: str | None = None
) -> None:
    for attempt in range(3):
        try:
            _assert_same_foreground(hwnd, process_name)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def wait_for_foreground(process_name: str, timeout: float = 3.0) -> bool:
    expected_process = ntpath.basename(process_name).casefold()
    if not expected_process:
        raise ValueError("process_name must be non-empty.")
    if timeout < 0:
        raise ValueError("timeout must be non-negative.")
    deadline = time.monotonic() + timeout
    while True:
        _hwnd, current_process = foreground_process()
        if current_process == expected_process:
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.1, remaining))


def capture_screen():
    """Capture the primary monitor in memory; no screenshot file is written."""
    try:
        import mss
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Screen capture requires the existing mss and Pillow packages.") from exc

    with mss.mss() as session:
        if len(session.monitors) < 2:
            raise RuntimeError("No desktop monitor is available for capture.")
        monitor = dict(session.monitors[1])
        shot = session.grab(monitor)
    image = Image.frombytes("RGB", shot.size, shot.rgb)
    return image, monitor


def perceptual_hash(image) -> str:
    """Compute a 64-bit DCT perceptual hash using the project's NumPy dependency."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Perceptual screen comparison requires Pillow and NumPy.") from exc

    pixels = np.asarray(
        image.convert("L").resize((32, 32), Image.Resampling.LANCZOS),
        dtype=np.float64,
    )
    axis = np.arange(32)
    frequencies = np.arange(8)[:, None]
    transform = np.cos(
        np.pi * (2 * axis[None, :] + 1) * frequencies / 64
    )
    transform *= math.sqrt(2 / 32)
    transform[0, :] = math.sqrt(1 / 32)
    coefficients = transform @ pixels @ transform.T
    low_frequency = coefficients[:8, :8].reshape(-1)
    median = float(np.median(low_frequency[1:]))
    value = sum(
        1 << index
        for index, coefficient in enumerate(low_frequency)
        if coefficient > median
    )
    return f"{value:016x}"


def screen_capture_metadata() -> dict[str, Any]:
    image, monitor = capture_screen()
    return {
        "width": image.width,
        "height": image.height,
        "left": int(monitor["left"]),
        "top": int(monitor["top"]),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "phash": perceptual_hash(image),
    }


def ocr_screen(
    language: str = "eng",
    min_confidence: float = 45.0,
    *,
    image=None,
    monitor: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise RuntimeError("Local OCR requires the existing pytesseract package.") from exc
    if image is None:
        image, monitor = capture_screen()
    elif monitor is None:
        raise ValueError("monitor metadata is required when OCR uses a supplied frame.")
    try:
        data = pytesseract.image_to_data(
            image,
            lang=language,
            output_type=Output.DICT,
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError(
            "Tesseract OCR is not installed; install Tesseract locally to use OCR."
        ) from exc

    results: list[dict[str, Any]] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = raw_text.strip()
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = 0.0
        if not text or confidence < min_confidence:
            continue
        results.append({
            "text": text[:300],
            "confidence": confidence,
            "x": int(monitor["left"]) + int(data["left"][index]),
            "y": int(monitor["top"]) + int(data["top"][index]),
            "width": int(data["width"][index]),
            "height": int(data["height"][index]),
        })
        if len(results) >= MAX_OCR_WORDS:
            break
    return results


def active_window_tree() -> dict[str, Any]:
    _require_windows()
    hwnd, process_name = foreground_process()
    if process_name not in allowed_processes():
        raise PermissionError(
            f"UI Automation is limited to allowlisted processes; got {process_name}."
        )
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("UI Automation requires the existing pywinauto package.") from exc

    window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
    rectangle = window.rectangle()
    controls = []
    for control in window.descendants():
        if not control.is_visible():
            continue
        info = control.element_info
        bounds = control.rectangle()
        controls.append({
            "name": str(info.name or "")[:300],
            "control_type": str(info.control_type or "")[:80],
            "x": int(bounds.left),
            "y": int(bounds.top),
            "width": int(bounds.width()),
            "height": int(bounds.height()),
            "enabled": bool(control.is_enabled()),
        })
        if len(controls) >= MAX_UIA_CONTROLS:
            break
    return {
        "title": window.window_text()[:300],
        "process": process_name,
        "bounds": {
            "x": int(rectangle.left),
            "y": int(rectangle.top),
            "width": int(rectangle.width()),
            "height": int(rectangle.height()),
        },
        "controls": controls,
        "truncated": len(controls) >= MAX_UIA_CONTROLS,
    }


def wait_for_screen_change(
    initial_hash: str | None = None,
    timeout: float = 10.0,
    poll_interval: float = 0.5,
    threshold: float = 0.08,
) -> dict[str, Any]:
    if not 0 < timeout <= 30:
        raise ValueError("timeout must be greater than 0 and no more than 30 seconds.")
    if not 0.1 <= poll_interval <= 2:
        raise ValueError("poll_interval must be between 0.1 and 2 seconds.")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1.")

    before = initial_hash or perceptual_hash(capture_screen()[0])
    if len(before) != 16:
        raise ValueError("initial_hash must be a 16-character perceptual hash.")
    started = time.monotonic()
    deadline = started + timeout
    after = before
    while time.monotonic() < deadline:
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        after = perceptual_hash(capture_screen()[0])
        changed_bits = (int(before, 16) ^ int(after, 16)).bit_count()
        if changed_bits / 64 > threshold:
            return {
                "changed": True,
                "before": before,
                "after": after,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
    return {
        "changed": False,
        "before": before,
        "after": after,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def click_uia_text(target: str, hwnd: int) -> str:
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("UI Automation requires the existing pywinauto package.") from exc
    wanted = " ".join(target.casefold().split())
    if not wanted:
        raise ValueError("target must contain visible control text.")

    window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
    matches = [
        control
        for control in window.descendants()
        if control.is_visible()
        and control.is_enabled()
        and " ".join(str(control.element_info.name or "").casefold().split()) == wanted
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one enabled visible control named {target!r}; found {len(matches)}."
        )
    _check_emergency_stop()
    _assert_same_foreground_with_retry(hwnd)
    matches[0].click_input()
    return "Clicked the matching UI Automation control."


def validate_input_request(parameters: dict[str, Any]) -> str:
    action = str(parameters.get("action", "")).strip().casefold()
    if action not in {"click", "click_text", "double_click", "drag", "move", "press", "hotkey", "scroll", "type", "type_text"}:
        raise ValueError(f"Unsupported computer input action: {action!r}.")

    if action in {"click", "double_click", "move"}:
        _coordinates(parameters, "x", "y")
    elif action == "drag":
        _coordinates(parameters, "x1", "y1")
        _coordinates(parameters, "x2", "y2")
    elif action == "click_text":
        if not isinstance(parameters.get("target"), str) or not parameters["target"].strip():
            raise ValueError("click_text requires a non-empty target.")
    elif action == "press":
        _validated_key(parameters.get("key"))
    elif action == "hotkey":
        _validated_hotkey(parameters.get("keys"))
    elif action == "scroll":
        direction = str(parameters.get("direction", "")).casefold()
        amount = parameters.get("amount", 1)
        if direction not in {"up", "down"}:
            raise ValueError("direction must be up or down.")
        if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 10:
            raise ValueError("amount must be an integer from 1 to 10.")
    elif action in {"type", "type_text"}:
        text = parameters.get("text")
        if not isinstance(text, str) or not text or len(text) > 1000:
            raise ValueError("text must contain between 1 and 1000 characters.")
    return action


def describe_input_request(parameters: dict[str, Any]) -> str:
    action = validate_input_request(parameters)
    if action in {"click", "double_click", "move"}:
        return f"{action} at ({parameters['x']}, {parameters['y']})"
    if action == "click_text":
        return f"click text {parameters['target']!r}"
    if action == "drag":
        return (
            f"drag from ({parameters['x1']}, {parameters['y1']}) "
            f"to ({parameters['x2']}, {parameters['y2']})"
        )
    if action == "press":
        return f"press {parameters['key']}"
    if action == "hotkey":
        return f"press shortcut {parameters['keys']}"
    if action == "scroll":
        return f"scroll {parameters.get('direction')} by {parameters.get('amount', 1)}"
    return f"type {len(parameters['text'])} characters"


def execute_input(parameters: dict[str, Any]) -> dict[str, Any]:
    action = validate_input_request(parameters)
    if parameters.get("confirmed") is not True:
        return {
            "result": "Ask the user for explicit confirmation",
            "action": describe_input_request(parameters),
        }

    arm_emergency_stop()
    _check_emergency_stop()
    hwnd, process_name = require_allowed_foreground()
    expected_hwnd = parameters.get("_expected_window")
    expected_process = parameters.get("_expected_process")
    if (
        expected_hwnd is not None
        and (hwnd != expected_hwnd or process_name != expected_process)
    ):
        raise PermissionError(
            "The foreground window changed after confirmation; no input was sent."
        )
    import pyautogui

    pyautogui.FAILSAFE = True
    result: str
    if action == "click_text":
        result = click_uia_text(parameters["target"], hwnd)
    elif action in {"click", "double_click", "move"}:
        x, y = parameters["x"], parameters["y"]
        _require_screen_coordinates(pyautogui, x, y)
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        if action == "click":
            pyautogui.click(x, y)
        elif action == "double_click":
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.moveTo(x, y)
        result = f"{action} at ({x}, {y})."
    elif action == "drag":
        x1, y1 = parameters["x1"], parameters["y1"]
        x2, y2 = parameters["x2"], parameters["y2"]
        _require_screen_coordinates(pyautogui, x1, y1)
        _require_screen_coordinates(pyautogui, x2, y2)
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        pyautogui.moveTo(x1, y1)
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        pyautogui.dragTo(x2, y2, button="left")
        result = f"Dragged from ({x1}, {y1}) to ({x2}, {y2})."
    elif action == "press":
        key = _validated_key(parameters["key"])
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        pyautogui.press(key)
        result = f"Pressed {key}."
    elif action == "hotkey":
        keys = _validated_hotkey(parameters["keys"])
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        pyautogui.hotkey(*keys)
        result = f"Pressed the {', '.join(keys)} shortcut."
    elif action == "scroll":
        direction = str(parameters.get("direction", "")).casefold()
        amount = parameters.get("amount", 1)
        _check_emergency_stop()
        _assert_same_foreground_with_retry(hwnd, process_name)
        pyautogui.scroll(amount if direction == "up" else -amount)
        result = f"Scrolled {direction} by {amount}."
    elif action in {"type", "type_text"}:
        text = parameters["text"]
        for character in text:
            _check_emergency_stop()
            _assert_same_foreground_with_retry(hwnd, process_name)
            pyautogui.write(character, interval=0)
        result = f"Typed {len(text)} characters."
    _check_emergency_stop()
    return {"result": result, "process": process_name}


def _coordinates(parameters: dict[str, Any], x_name: str, y_name: str) -> tuple[int, int]:
    x, y = parameters.get(x_name), parameters.get(y_name)
    if (
        isinstance(x, bool)
        or not isinstance(x, int)
        or isinstance(y, bool)
        or not isinstance(y, int)
    ):
        raise ValueError(f"{x_name} and {y_name} must be integer screen coordinates.")
    return x, y


def _require_screen_coordinates(pyautogui, x: int, y: int) -> None:
    width, height = pyautogui.size()
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside the primary screen ({width}, {height})."
        )


_KEYS = frozenset(
    {"enter", "tab", "esc", "escape", "backspace", "delete", "space", "up", "down",
     "left", "right", "home", "end", "pageup", "pagedown"}
    | {f"f{index}" for index in range(1, 13)}
    | {chr(code) for code in range(ord("a"), ord("z") + 1)}
    | {str(index) for index in range(10)}
)
_MODIFIERS = frozenset({"ctrl", "alt", "shift", "win"})


def _validated_key(value: Any) -> str:
    key = str(value or "").strip().casefold()
    if key not in _KEYS:
        raise ValueError(f"Unsupported key: {key!r}.")
    return "esc" if key == "escape" else key


def _validated_hotkey(value: Any) -> list[str]:
    if not isinstance(value, str):
        raise ValueError("keys must be a plus-separated shortcut string.")
    keys = [key.strip().casefold() for key in value.split("+")]
    if (
        len(keys) < 2
        or len(keys) > 4
        or any(not key for key in keys)
        or any(key not in _MODIFIERS and key not in _KEYS for key in keys)
        or len(set(keys)) != len(keys)
        or not all(key in _MODIFIERS for key in keys[:-1])
        or keys[-1] in _MODIFIERS
    ):
        raise ValueError("hotkey must be a modifier combination plus one supported key.")
    return ["esc" if key == "escape" else key for key in keys]

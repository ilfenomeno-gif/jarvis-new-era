"""External UI automation helpers for live Jarvis checks."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from pywinauto import Application, Desktop


PROJECT_ROOT = Path(__file__).resolve().parents[2]
E2E_ROOT = Path(__file__).resolve().parent
LOG_DIR = E2E_ROOT / "logs"
SCREENSHOT_DIR = E2E_ROOT / "screenshots"
AUDIT_LOG = PROJECT_ROOT / "logs" / "app_launcher.log"
INPUT_AUTOMATION_ID = (
    "QApplication.jarvisMainWindow.dock_input.QWidget.QLineEdit"
)
ACTIVITY_LOG_AUTOMATION_ID = (
    "QApplication.jarvisMainWindow.dock_activity_log.QWidget.LogWidget"
)


def _pid_snapshot() -> set[int]:
    return set(psutil.pids())


class JarvisHarness:
    """Starts Jarvis and drives only its accessible UI controls."""

    def __init__(self) -> None:
        self.timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.process: subprocess.Popen | None = None
        self.window = None
        self.log_path = LOG_DIR / f"jarvis-{self.timestamp}.log"
        self._log_handle = None
        self._pid_before: set[int] = set()
        self._managed_jarvis_pids: set[int] = set()
        self._app_pids: set[int] = set()
        self._screenshot_paths: list[str] = []
        self._audit_count_before = 0
        self._started_at = 0.0
        self._response_timeout = 90.0

    def start(self) -> None:
        if self.process is not None:
            raise RuntimeError("JarvisHarness instances can only be started once.")

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        self._pid_before = self.processes_before()
        self._audit_count_before = len(self.read_audit_log())
        self._started_at = time.monotonic()
        env = os.environ.copy()
        env["JARVIS_3D_PREWARM"] = "0"
        env["PYTHONUNBUFFERED"] = "1"
        python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise FileNotFoundError(f"Jarvis virtualenv interpreter not found: {python}")

        self._log_handle = self.log_path.open("w", encoding="utf-8", errors="replace")
        try:
            self.process = subprocess.Popen(
                [str(python), "main.py"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._wait_for_window(timeout=90)
        except Exception:
            self.stop()
            raise

    def _refresh_process_tree(self) -> set[int]:
        if self.process is None:
            return set()
        pids = {self.process.pid}
        try:
            root = psutil.Process(self.process.pid)
            pids.update(child.pid for child in root.children(recursive=True))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        self._managed_jarvis_pids.update(pids - self._pid_before)
        return pids

    def _wait_for_window(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is None:
                raise RuntimeError("Jarvis process was not started.")
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Jarvis exited with code {self.process.returncode}.\n"
                    f"{self.read_log_tail()}"
                )
            process_tree = self._refresh_process_tree()
            for candidate in Desktop(backend="uia").windows(visible_only=True):
                try:
                    if candidate.process_id() not in process_tree:
                        continue
                    title = candidate.window_text()
                    if "JARVIS" not in title.upper() and "MARK LII" not in title.upper():
                        continue
                    self.window = Desktop(backend="uia").window(handle=candidate.handle)
                    return
                except (RuntimeError, OSError):
                    continue
            time.sleep(0.25)
        raise TimeoutError(
            "Timed out waiting for Jarvis' accessible desktop window.\n"
            f"{self.read_log_tail()}"
        )

    def wait_online(self, timeout: float = 30) -> bool:
        """Wait for the exact online marker in Jarvis' visible activity log."""
        self._require_window()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if "jarvis online" in self._read_activity_log().casefold():
                return True
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"Jarvis exited before coming online (code {self.process.returncode}).\n"
                    f"{self.read_log_tail()}"
                )
            time.sleep(0.25)
        raise TimeoutError(
            f"Jarvis did not report 'JARVIS online' within {timeout:g}s.\n"
            f"Activity log:\n{self._read_activity_log()[-2000:]}\n"
            f"Process log:\n{self.read_log_tail()}"
        )

    def _require_window(self):
        if self.window is None:
            raise RuntimeError("Jarvis window is not connected; call start() first.")
        return self.window

    def _read_activity_log(self) -> str:
        window = self._require_window()
        control = window.child_window(
            auto_id=ACTIVITY_LOG_AUTOMATION_ID,
            control_type="Edit",
        ).wrapper_object()
        for read in (
            lambda: control.get_value(),
            lambda: control.iface_value.CurrentValue,
            lambda: "\n".join(control.texts()),
            lambda: control.window_text(),
        ):
            try:
                value = read()
            except (AttributeError, RuntimeError, OSError):
                continue
            if value:
                return str(value)
        raise RuntimeError("Jarvis activity log is not readable through UI Automation.")

    def mute_microphone(self) -> None:
        window = self._require_window()
        active = window.child_window(
            title_re=".*MICROPHONE ACTIVE.*",
            control_type="Button",
        )
        if not active.exists(timeout=3):
            raise RuntimeError("The accessible MICROPHONE ACTIVE button was not found.")
        active.click_input()
        muted = window.child_window(
            title_re=".*MICROPHONE MUTED.*",
            control_type="Button",
        )
        if not muted.wait("exists enabled visible", timeout=5):
            raise RuntimeError("Microphone button did not change to MUTED.")

    def send_command(self, text: str, timeout: float | None = None) -> str:
        if not text.strip():
            raise ValueError("Command text cannot be empty.")
        window = self._require_window()
        before_ui = self._read_activity_log()
        before_stdout = self._read_process_log()
        input_box = window.child_window(
            auto_id=INPUT_AUTOMATION_ID,
            control_type="Edit",
        )
        if not input_box.exists(timeout=3):
            raise RuntimeError("The accessible Jarvis command input was not found.")
        input_box.set_edit_text(text)
        input_box.type_keys("{ENTER}")

        deadline = time.monotonic() + (timeout or self._response_timeout)
        user_marker = f"You: {text}".casefold()
        while time.monotonic() < deadline:
            activity = self._read_activity_log()
            process_log = self._read_process_log()
            submitted = user_marker in activity.casefold()
            new_ui = activity[len(before_ui):] if activity.startswith(before_ui) else activity
            new_stdout = (
                process_log[len(before_stdout):]
                if process_log.startswith(before_stdout)
                else process_log
            )
            responded = (
                "jarvis:" in new_ui.casefold()
                or "[jarvis] 📤" in new_stdout.casefold()
                or "[jarvis] ❌ recv:" in new_stdout.casefold()
                or "[jarvis] error (" in new_stdout.casefold()
            )
            if submitted and responded:
                return f"{new_ui}\n{new_stdout}".strip()
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"Jarvis exited while processing command {text!r}.\n"
                    f"{self.read_log_tail()}"
                )
            time.sleep(0.25)
        raise TimeoutError(
            f"Jarvis did not respond to {text!r} within {timeout or self._response_timeout:g}s.\n"
            f"Activity log:\n{self._read_activity_log()[-2000:]}\n"
            f"Process log:\n{self.read_log_tail()}"
        )

    def screenshot(self, name: str) -> str:
        window = self._require_window()
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "capture"
        path = SCREENSHOT_DIR / f"{self.timestamp}-{safe_name}.png"
        window.set_focus()
        time.sleep(0.2)
        window.capture_as_image().save(path)
        self._screenshot_paths.append(str(path.relative_to(PROJECT_ROOT)))
        return str(path)

    def read_log_tail(self, lines: int = 100) -> str:
        if lines < 1:
            raise ValueError("lines must be positive.")
        return "\n".join(self._read_process_log().splitlines()[-lines:])

    def _read_process_log(self) -> str:
        if not self.log_path.is_file():
            return ""
        if self._log_handle is not None:
            self._log_handle.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def read_audit_log(self) -> list[dict[str, Any]]:
        if not AUDIT_LOG.is_file():
            return []
        entries: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            AUDIT_LOG.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"Audit entry on line {line_number} is not an object.")
                entries.append(value)
        return entries

    def processes_before(self) -> set[int]:
        return _pid_snapshot()

    def processes_after(self) -> set[int]:
        return _pid_snapshot()

    def verify_app_launched(self, name: str, timeout: float = 10) -> int:
        aliases = {
            "calc": {"calc.exe", "calculatorapp.exe", "microsoft.windowscalculator.exe"},
            "calc.exe": {"calc.exe", "calculatorapp.exe", "microsoft.windowscalculator.exe"},
        }
        expected = aliases.get(name.casefold(), {Path(name).name.casefold()})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for pid in self.processes_after() - self._pid_before:
                try:
                    process = psutil.Process(pid)
                    if (
                        process.name().casefold() in expected
                        and process.create_time() >= self._started_at
                    ):
                        self._app_pids.add(pid)
                        return pid
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            time.sleep(0.2)
        raise TimeoutError(
            f"No new process matching {name!r} appeared within {timeout:g}s."
        )

    def wait_for_ui_text(self, text: str, timeout: float = 20) -> str:
        window = self._require_window()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for control in window.descendants():
                try:
                    visible_text = control.window_text()
                except (RuntimeError, OSError):
                    continue
                if text.casefold() in visible_text.casefold():
                    return visible_text
            time.sleep(0.25)
        raise TimeoutError(f"Jarvis UI did not expose the text {text!r}.")

    def report_data(self) -> dict[str, Any]:
        self._refresh_process_tree()
        activity_log = self._read_activity_log() if self.window is not None else ""
        return {
            "screenshots": list(self._screenshot_paths),
            "log_excerpt": (
                "=== Jarvis activity log ===\n"
                f"{activity_log[-6000:]}\n\n"
                "=== Process log ===\n"
                f"{self.read_log_tail(100)}"
            ),
            "pid_new": sorted(
                (self._managed_jarvis_pids | self._app_pids) - self._pid_before
            ),
            "log_path": str(self.log_path.relative_to(PROJECT_ROOT)),
        }

    def _close_pid(self, pid: int, timeout: float = 5) -> None:
        try:
            process = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return
        for candidate in Desktop(backend="uia").windows(visible_only=True):
            try:
                if candidate.process_id() == pid:
                    Desktop(backend="uia").window(handle=candidate.handle).close()
            except (RuntimeError, OSError):
                continue
        try:
            process.wait(timeout=timeout)
            return
        except psutil.TimeoutExpired:
            pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except psutil.NoSuchProcess:
            return
        except psutil.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=3)
            except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                pass

    def stop(self) -> None:
        for pid in sorted(self._app_pids):
            self._close_pid(pid)

        self._refresh_process_tree()
        if self.window is not None:
            try:
                self.window.close()
            except (RuntimeError, OSError):
                pass

        if self.process is not None:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)

        self._refresh_process_tree()
        for pid in sorted(self._managed_jarvis_pids, reverse=True):
            self._close_pid(pid, timeout=2)

        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

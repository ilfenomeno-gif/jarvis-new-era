"""Live Jarvis E2E scenarios, runnable directly or through pytest."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.e2e.harness import JarvisHarness
from core.pattern_learner import get_hints_for


def _finish(request, harness: JarvisHarness) -> None:
    try:
        if harness.window is not None and not harness._screenshot_paths:
            harness.screenshot(f"failure-{request.node.name}")
    except Exception as exc:
        request.node.user_properties.append(("e2e_screenshot_error", str(exc)))
    finally:
        try:
            result = harness.report_data()
        except Exception as exc:
            result = {"report_data_error": str(exc)}
        finally:
            try:
                harness.stop()
            finally:
                request.node.user_properties.append(
                    ("e2e_result", json.dumps(result, ensure_ascii=False))
                )


def _start_for_text(harness: JarvisHarness) -> None:
    harness.start()
    harness.wait_online(timeout=30)
    harness.mute_microphone()


def _new_audit_entries(harness: JarvisHarness) -> list[dict]:
    return harness.read_audit_log()[harness._audit_count_before:]


def _confirm_app_launch(harness: JarvisHarness, phrase: str) -> str:
    first = harness.send_command(phrase)
    if not re.search(r"confirm|conferm", first, re.IGNORECASE):
        raise AssertionError(
            "Jarvis did not request explicit confirmation; refusing to send approval."
        )
    return harness.send_command("Sì, confermo l'apertura dell'applicazione richiesta.")


def _feature_available(path: Path, pattern: str) -> bool:
    return path.is_file() and re.search(
        pattern, path.read_text(encoding="utf-8", errors="replace"), re.IGNORECASE
    ) is not None


def _gpu_skip_reason() -> str | None:
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return "nvidia-smi is unavailable; GPU availability cannot be established."
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"GPU availability check failed: {exc}"
    readings = []
    for line in result.stdout.splitlines():
        try:
            utilization, used, total = (int(value.strip()) for value in line.split(","))
        except ValueError:
            return f"Unrecognized nvidia-smi output: {line!r}"
        readings.append((utilization, used, total))
    if not readings:
        return "nvidia-smi did not report a GPU."
    busy = [
        (util, used, total)
        for util, used, total in readings
        if util >= 20 or (total > 0 and used / total >= 0.5)
    ]
    if busy:
        return f"GPU is busy: {busy!r}"
    return None


def _wait_for_log_text(
    harness: JarvisHarness,
    text: str,
    timeout: float = 10,
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        log = harness.read_log_tail(300)
        if text.casefold() in log.casefold():
            return log
        time.sleep(0.25)
    raise AssertionError(
        f"Process log did not contain {text!r} within {timeout:g}s:\n"
        f"{harness.read_log_tail(300)}"
    )


def test_jarvis_starts(request):
    harness = JarvisHarness()
    try:
        harness.start()
        assert harness.wait_online(timeout=30)
        harness.screenshot("idle")
    finally:
        _finish(request, harness)


def test_microphone_mute(request):
    harness = JarvisHarness()
    try:
        harness.start()
        harness.mute_microphone()
        harness.screenshot("microphone-muted")
    finally:
        _finish(request, harness)


def test_open_notepad_via_text(request):
    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        response = _confirm_app_launch(harness, "apri il blocco note")
        assert "not found" not in response.casefold(), (
            f"Jarvis could not resolve Notepad: {response}"
        )
        pid = harness.verify_app_launched("notepad.exe", timeout=10)
        entries = _new_audit_entries(harness)
        assert any(
            entry.get("event") in {"launch_requested", "launch_started"}
            and "notepad" in str(entry.get("app", "")).casefold()
            for entry in entries
        ), f"No Notepad launch audit event found: {entries!r}"
        harness._app_pids.add(pid)
        harness.screenshot("notepad-open")
    finally:
        _finish(request, harness)


def test_open_calc_via_text(request):
    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        response = _confirm_app_launch(harness, "apri la calcolatrice")
        assert "not found" not in response.casefold(), (
            f"Jarvis could not resolve Calculator: {response}"
        )
        pid = harness.verify_app_launched("calc.exe", timeout=10)
        entries = _new_audit_entries(harness)
        assert any(
            entry.get("event") in {"launch_requested", "launch_started"}
            and "calc" in str(entry.get("app", "")).casefold()
            for entry in entries
        ), f"No Calculator launch audit event found: {entries!r}"
        harness._app_pids.add(pid)
        harness.screenshot("calculator-open")
    finally:
        _finish(request, harness)


def test_open_pc_cad(request):
    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        harness.send_command("carica il PC CAD")
        _wait_for_log_text(harness, "[JARVIS] 📞 viewer_3d")
        harness.wait_for_ui_text("MODEL READY", timeout=30)
        harness.screenshot("pc-cad-viewer")
    finally:
        _finish(request, harness)


def test_physics_drop(request):
    viewer_source = (
        PROJECT_ROOT / "assets" / "viewer3d" / "src" / "viewer.js"
    )
    if not _feature_available(viewer_source, r"RAPIER|applyPhysics"):
        pytest.skip("Rapier physics is not present in the current main checkout.")
    reason = _gpu_skip_reason()
    if reason:
        pytest.skip(reason)

    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        output = harness.send_command("carica il PC e fallo cadere")
        log = _wait_for_log_text(harness, "apply_physics")
        harness.wait_for_ui_text("MODEL READY", timeout=30)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and "drop" not in (
            output + log + harness.read_log_tail(300)
        ).casefold():
            time.sleep(0.25)
        assert "drop" in (output + log + harness.read_log_tail(300)).casefold(), (
            "The live log did not show a drop-physics result."
        )
        harness.screenshot("physics-drop")
    finally:
        _finish(request, harness)


def test_clipping(request):
    viewer_source = PROJECT_ROOT / "assets" / "viewer3d" / "src" / "viewer.js"
    if not _feature_available(viewer_source, r"setClipping"):
        pytest.skip("The viewer clipping implementation is not present.")

    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        harness.send_command("carica il PC CAD")
        _wait_for_log_text(harness, "Model cad/pc.glb loaded")
        harness.send_command("taglia il PC a metà")
        _wait_for_log_text(harness, "set_clipping")
        _wait_for_log_text(harness, "Clipping enabled")
        harness.screenshot("clipping")
    finally:
        _finish(request, harness)


def test_pattern_learner_hint(request):
    if "realistic" not in get_hints_for("3d").casefold():
        pytest.skip(
            "No learned realistic-style hint is available in the active pattern state."
        )

    harness = JarvisHarness()
    try:
        _start_for_text(harness)
        harness.send_command("carica il PC CAD")
        _wait_for_log_text(harness, "[JARVIS] 📞 viewer_3d")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if "realistic" in harness.read_log_tail(300).casefold():
                break
            time.sleep(0.25)
        assert "realistic" in harness.read_log_tail(300).casefold(), (
            "The process log did not expose the learned realistic-style hint or "
            "the resulting style action."
        )
        harness.screenshot("pattern-realistic")
    finally:
        _finish(request, harness)


def main() -> int:
    return int(pytest.main([str(Path(__file__)), "-v", "-s"]))


if __name__ == "__main__":
    raise SystemExit(main())

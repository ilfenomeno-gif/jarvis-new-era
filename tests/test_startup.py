from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
HUD_HOST = "127.0.0.1"
HUD_PORT = int(os.environ.get("JARVIS_HUD_PORT", "8765"))
HUD_URL = f"http://{HUD_HOST}:{HUD_PORT}/"


def _hud_port_is_occupied() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.settimeout(0.25)
        return listener.connect_ex((HUD_HOST, HUD_PORT)) == 0


@pytest.mark.live
@pytest.mark.timeout(60)
def test_offscreen_cold_start_serves_hud(temp_profile: Path):
    if _hud_port_is_occupied():
        pytest.skip(f"HUD port {HUD_PORT} is already in use.")

    environment = os.environ.copy()
    environment.update(
        {
            "QT_QPA_PLATFORM": "offscreen",
            "JARVIS_UI_LAYOUT": str(temp_profile / "ui_layout.json"),
            "JARVIS_LOG_LEVEL": "DEBUG",
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "main.py",
            "--startup-smoke",
            "--hud-port",
            str(HUD_PORT),
        ],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
    try:
        deadline = time.monotonic() + 45
        response_ok = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                output += process.stdout.read() if process.stdout else ""
                pytest.fail(
                    f"Startup smoke process exited with {process.returncode}:\n{output}"
                )
            try:
                with urlopen(HUD_URL, timeout=1) as response:
                    response_ok = response.status == 200
                if response_ok:
                    break
            except (OSError, URLError):
                time.sleep(0.1)

        assert response_ok, "HUD did not become ready within 45 seconds."
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            tail, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            tail, _ = process.communicate(timeout=5)
        output += tail or ""

    assert "JARVIS_STARTUP_READY" in output

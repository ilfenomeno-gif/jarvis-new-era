"""Headless tests for the reactive HUD states and reduced-motion mode."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from core.animations import ScanlineOverlay, start_pulsing_glow
from ui import HudCanvas, JarvisUI, MainWindow, _JARVIS_VISUAL_STATES


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_jarvis_state_api_accepts_only_supported_states():
    class _Signal:
        def __init__(self):
            self.emitted = []

        def emit(self, value):
            self.emitted.append(value)

    signal = _Signal()
    ui = JarvisUI.__new__(JarvisUI)
    ui._win = SimpleNamespace(_state_sig=signal)

    for state in sorted(_JARVIS_VISUAL_STATES):
        ui.set_jarvis_state(state)

    assert signal.emitted == [state.upper() for state in sorted(_JARVIS_VISUAL_STATES)]
    with pytest.raises(ValueError, match="state must be one of"):
        ui.set_jarvis_state("unknown")


def test_hud_state_transitions_select_distinct_visual_modes(app, monkeypatch):
    monkeypatch.delenv("JARVIS_REDUCED_MOTION", raising=False)
    hud = HudCanvas("")
    hud.stop_animations()
    assert hud._tmr.interval() == 17

    hud.set_jarvis_state("idle")
    assert hud.motion_state == "idle"

    idle_rings = list(hud._rings)
    hud._step()
    idle_rotation = hud._rings[0] - idle_rings[0]

    hud.set_jarvis_state("thinking")
    thinking_rings = list(hud._rings)
    hud._step()
    thinking_rotation = hud._rings[0] - thinking_rings[0]

    assert hud.motion_state == "thinking"
    assert thinking_rotation > idle_rotation

    hud.set_jarvis_state("speaking")
    assert hud.motion_state == "speaking"
    hud.set_jarvis_state("listening")
    assert hud.motion_state == "listening"
    hud.set_jarvis_state("error")
    assert hud.motion_state == "error"
    hud.close()


def test_error_log_switches_hud_to_error_state(app):
    class _Hud:
        state = "LISTENING"
        speaking = False

        def set_jarvis_state(self, state):
            self.motion_state = state

    class _Log:
        def __init__(self):
            self.messages = []

        def append_log(self, text):
            self.messages.append(text)

    window = SimpleNamespace(hud=_Hud(), _log=_Log())
    window._apply_state = lambda state: MainWindow._apply_state(window, state)

    MainWindow._on_log_message(window, "ERR: simulated failure")

    assert window._log.messages == ["ERR: simulated failure"]
    assert window.hud.motion_state == "error"
    assert window.hud.state == "ERROR"


def test_reduced_motion_disables_heavy_hud_animation_and_stops_timer(
    app, monkeypatch
):
    monkeypatch.setenv("JARVIS_REDUCED_MOTION", "1")
    hud = HudCanvas("")

    assert hud.reduced_motion is True
    assert hud._tmr.interval() == 33
    hud.stop_animations()
    assert not hud._tmr.isActive()

    rings = list(hud._rings)
    scans = (hud._scan, hud._scan2)
    hud._step()
    assert hud._rings == rings
    assert (hud._scan, hud._scan2) == scans
    assert hud._pulses == []
    assert hud._particles == []

    hud.close()


def test_title_glow_and_scanline_start_and_stop(app):
    parent = QWidget()
    title = QLabel("JARVIS", parent)
    glow = start_pulsing_glow(title, "#00d4ff")
    scanline = ScanlineOverlay(parent, "#00d4ff")

    assert glow is not None
    assert glow.state() == glow.State.Running
    assert scanline._timer.isActive()
    assert scanline.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    glow.stop()
    scanline.stop()
    assert not scanline._timer.isActive()
    parent.close()


def test_reduced_motion_skips_title_glow_and_scanline_timer(app):
    parent = QWidget()
    title = QLabel("JARVIS", parent)

    assert start_pulsing_glow(title, "#00d4ff", reduced_motion=True) is None
    scanline = ScanlineOverlay(parent, "#00d4ff", reduced_motion=True)

    assert not scanline._timer.isActive()
    assert scanline.isHidden()
    scanline.stop()
    parent.close()


def test_main_window_loads_palette_aware_theme_stylesheet():
    styles = []
    window = SimpleNamespace(setStyleSheet=styles.append)

    MainWindow._apply_theme(window)

    assert len(styles) == 1
    assert "qlineargradient" in styles[0]
    assert "@BG@" not in styles[0]

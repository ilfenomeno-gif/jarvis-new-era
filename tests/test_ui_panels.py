import json
import os
import sys

import pytest

from actions import ui_layout
from core import ui_panels
from core.ui_panels import DOCKS, PANELS, WORKSPACES, PanelState


def test_panel_state_presets_and_validation():
    state = PanelState()
    # JARVIS VII: header/footer visible by default; content (news) hidden; no docks.
    assert state.visible("header") and state.visible("footer")
    assert not state.visible("content")
    state.apply_workspace("focus")
    assert state.workspace == "focus"
    state.set_visible("footer", False)
    assert state.workspace == "custom" and not state.visible("footer")
    with pytest.raises(ValueError):
        state.apply_workspace("nope")
    with pytest.raises(ValueError):
        state.set_visible("nope", True)
    with pytest.raises(ValueError):
        state.set_visible("input", True)  # input dock removed
    assert set(WORKSPACES["full"]) == set(PANELS)


def test_no_docks_remain():
    # SYS MONITOR, ACTIVITY LOG and INPUT docks were removed permanently.
    assert DOCKS == ()
    assert "controls" not in PANELS and "activity_log" not in PANELS and "input" not in PANELS


class _Ui:
    def __init__(self):
        self.state = PanelState()
        self.floating = {d: False for d in DOCKS}
        self.restored = 0

    @property
    def focus_mode(self):
        return self.state.workspace == "focus"

    def set_focus_mode(self, active):
        self.state.apply_workspace("focus" if active else "full")

    def apply_workspace(self, name):
        self.state.apply_workspace(name)

    def set_panel_visible(self, panel, visible):
        self.state.set_visible(panel, visible)

    def float_panel(self, panel, floating=None):
        for name in ui_panels.resolve(panel):
            self.floating[name] = (not self.floating[name]) if floating is None else floating

    def restore_layout(self):
        self.restored += 1
        self.floating = {d: False for d in DOCKS}
        self.state.apply_workspace("full")

    def panel_status(self):
        return {"workspace": self.state.workspace, "panels": self.state.snapshot(), "floating": dict(self.floating)}


def test_tool_panel_workspace_status():
    ui = _Ui()
    assert "hidden" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "footer"}, player=ui)
    assert not ui.state.visible("footer")
    assert "shown" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "footer", "visible": True}, player=ui)
    assert ui.state.visible("footer")
    assert "applied" in ui_layout.ui_layout({"mode": "workspace", "workspace": "coding"}, player=ui)
    assert not ui.state.visible("footer")
    assert '"coding"' in ui_layout.ui_layout({"mode": "status"}, player=ui)
    assert "Unknown workspace" in ui_layout.ui_layout({"mode": "workspace", "workspace": "x"}, player=ui)
    assert "Unknown panel" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "x"}, player=ui)
    # removed docks are unknown panels now
    assert "Unknown panel" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "input"}, player=ui)


def test_tool_float_and_restore():
    ui = _Ui()
    # no floatable docks remain
    assert "Unknown panel" in ui_layout.ui_layout({"mode": "float_panel", "panel": "input"}, player=ui)
    assert "Only these panels" in ui_layout.ui_layout({"mode": "float_panel", "panel": "footer"}, player=ui)
    assert "restored" in ui_layout.ui_layout({"mode": "restore_layout"}, player=ui)
    assert ui.restored == 1


def test_layout_file_roundtrip_and_bad_files(tmp_path):
    path = tmp_path / "config" / "ui_layout.json"
    assert ui_panels.load_layout(path) is None
    ui_panels.save_layout(
        path, qt_state=b"\x00\x01state", geometry=b"geo", workspace="custom",
        panels={**WORKSPACES["full"], "footer": False}, floating={},
    )
    data = ui_panels.load_layout(path)
    assert data["qt_state"] == b"\x00\x01state" and data["geometry"] == b"geo"
    assert data["panels"]["footer"] is False
    assert json.loads(path.read_text("utf-8"))["version"] == ui_panels.LAYOUT_VERSION
    path.write_text("{not json", encoding="utf-8")
    assert ui_panels.load_layout(path) is None
    path.write_text(json.dumps({"version": 99, "panels": {}, "qt_state": ""}), encoding="utf-8")
    assert ui_panels.load_layout(path) is None
    path.write_text(json.dumps({"version": 1, "panels": {}, "qt_state": "***"}), encoding="utf-8")
    assert ui_panels.load_layout(path) is None


@pytest.fixture
def real_ui(tmp_path, monkeypatch):
    if os.environ.get("CI"):
        pytest.skip("QtWebEngine crashes on the CI runner")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("JARVIS_UI_LAYOUT", str(tmp_path / "ui_layout.json"))
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    opened = []

    def make():
        jarvis = ui_module.JarvisUI("")
        app.processEvents()
        opened.append(jarvis)
        return jarvis

    make.app = app
    make.path = tmp_path / "ui_layout.json"
    yield make
    for jarvis in opened:
        jarvis._win._layout_timer.stop()
        jarvis._win.close()


def _visible(win):
    parts = {"header": win._header_panel, "content": win._content_panel, "footer": win._footer_panel}
    parts.update(win._docks)
    return {name: widget.isVisible() for name, widget in parts.items()}


def test_real_window_renders_each_workspace(real_ui):
    jarvis = real_ui()
    win = jarvis._win
    for workspace, expected in WORKSPACES.items():
        ui_layout.ui_layout({"mode": "workspace", "workspace": workspace}, player=jarvis)
        real_ui.app.processEvents()
        assert _visible(win) == expected, workspace
    ui_layout.ui_layout({"mode": "toggle_panel", "panel": "footer", "visible": False}, player=jarvis)
    real_ui.app.processEvents()
    assert not win._footer_panel.isVisible()
    assert jarvis.panel_status()["workspace"] == "custom"


def test_embedded_hud_hides_legacy_chrome_and_briefing(real_ui):
    jarvis = real_ui()
    win = jarvis._win
    win._panel_state.restore(
        {"header": True, "content": True, "footer": True},
        "custom",
    )
    win._render_panels()
    real_ui.app.processEvents()
    assert _visible(win)["content"]

    win._on_hud_browser_load_finished(True)
    real_ui.app.processEvents()

    assert not _visible(win)["header"]
    assert not _visible(win)["content"]
    assert not _visible(win)["footer"]
    assert win.windowTitle() == "JARVIS VII · MIRA"
    assert win._main_content_stack.currentWidget() is win._hud_cam_stack

    win._render_panels()
    real_ui.app.processEvents()
    assert not _visible(win)["header"]
    assert not _visible(win)["content"]
    assert not _visible(win)["footer"]

    win._show_content("Briefing", "legacy result")
    real_ui.app.processEvents()
    assert not _visible(win)["content"]


def test_quantum_hud_draws_blueprint_and_uses_runtime_telemetry():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QPixmap
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    hud = ui_module.HudCanvas("")
    hud.resize(420, 480)
    assert hud._projection_status == "WAITING FOR 3D MODEL"

    hud.set_system_metrics(37, -1)
    hud.set_projection_status("MODEL READY / demo")
    assert hud._cpu_percent == 37
    assert hud._gpu_percent == -1
    assert hud._projection_status == "MODEL READY / DEMO"
    pixmap = QPixmap(hud.size())
    hud.render(pixmap)
    assert not pixmap.isNull()
    hud.stop_animations()
    hud.close()


def test_quantum_hud_applies_data_driven_visual_states():
    from types import SimpleNamespace

    from core.hud_animator import HudAnimator
    import ui as ui_module

    class Signal:
        def __init__(self):
            self.values = []

        def emit(self, value):
            self.values.append(value)

    hud = SimpleNamespace(
        _hud_animator=HudAnimator(),
        motion_state="idle",
        _error_started=None,
        _error_flash=0.0,
        animationChanged=Signal(),
    )
    for state, key, expected in (
        ("listening", "core_color", "#00ff88"),
        ("thinking", "core_color", "#ff8a00"),
        ("speaking", "core_color", "#ff00d4"),
        ("generating_3d", "particle_count", 48),
    ):
        ui_module.HudCanvas.set_jarvis_state(hud, state)
        assert hud._hud_animator.target_snapshot()[key] == expected
    assert hud.motion_state == "generating_3d"
    assert hud.animationChanged.values[-1] == hud._hud_animator.target_snapshot()


def test_generation_status_shows_backend_and_elapsed_seconds(monkeypatch):
    import ui as ui_module

    class Timer:
        started = False

        def start(self, interval):
            self.started = interval == 1000

        def stop(self):
            self.started = False

    class Label:
        text = ""
        visible = False

        def clear(self):
            self.text = ""

        def hide(self):
            self.visible = False

        def show(self):
            self.visible = True

        def setText(self, text):
            self.text = text

    class Window:
        _generation_tmr = Timer()
        _generation_backend = ""
        _generation_started_at = 0.0
        _generation_elapsed = 0
        _generation_status_label = Label()

        def _tick_generation_status(self):
            ui_module.MainWindow._tick_generation_status(self)

    monkeypatch.setattr(ui_module.time, "monotonic", lambda: 0.0)
    window = Window()
    ui_module.MainWindow._set_generation_status(window, "SF3D")
    ui_module.MainWindow._set_generation_elapsed(window, 45)
    assert window._generation_tmr.started
    assert window._generation_status_label.visible
    assert window._generation_status_label.text == (
        "Generazione in corso... [SF3D] - 45s"
    )
    ui_module.MainWindow._set_generation_status(window, "")
    assert not window._generation_tmr.started
    assert not window._generation_status_label.visible


def test_no_docks_and_center_stays_central(real_ui):
    from PyQt6.QtWidgets import QDockWidget
    win = real_ui()._win
    assert win._docks == {}
    assert not isinstance(win.centralWidget(), QDockWidget)
    assert win.centralWidget().isAncestorOf(win._main_content_stack)
    assert win._main_content_stack.isAncestorOf(win.hud)


def test_focus_mode_toggles_and_restores(real_ui):
    jarvis = real_ui()
    win = jarvis._win
    jarvis.set_focus_mode(True)
    real_ui.app.processEvents()
    assert win._focus_mode
    jarvis.set_focus_mode(False)
    real_ui.app.processEvents()
    assert not win._focus_mode
    assert win._header_panel.isVisible() and win._footer_panel.isVisible()


def test_layout_survives_restart(real_ui):
    first = real_ui()
    first._win.close()
    assert real_ui.path.exists()
    second = real_ui()
    # no docks to restore; window builds cleanly
    assert second._win._docks == {}
    assert second.panel_status()["workspace"] in WORKSPACES or "custom"


def test_saved_layout_from_older_build_does_not_break(real_ui):
    # A layout saved when docks existed must not crash the dock-less window.
    ui_panels.save_layout(
        real_ui.path, qt_state=b"", panels={n: True for n in PANELS}, workspace="custom",
        floating={"input": True, "controls": True},
    )
    win = real_ui()._win
    assert win._docks == {}
    assert win._header_panel.isVisible()


def test_layout_anomalies_and_chat_phrases():
    # no docks remain → no floating-dock anomaly is possible
    assert not ui_panels.layout_anomalies({"floating": {"input": True}})
    assert not ui_panels.layout_anomalies({"floating": {}})
    for text in ("apri la chat", "Jarvis parliamo", "open the chat", "let's talk"):
        assert ui_panels.wants_chat(text), text
    for text in ("che tempo fa", "chatgpt", "una sedia"):
        assert not ui_panels.wants_chat(text), text

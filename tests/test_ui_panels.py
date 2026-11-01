import json
import os
import sys

import pytest

from actions import ui_layout
from core import ui_panels
from core.ui_panels import DOCKS, PANELS, WORKSPACES, PanelState


def test_panel_state_presets_and_validation():
    state = PanelState()
    assert all(state.visible(p) for p in PANELS)
    state.apply_workspace("focus")
    assert not any(state.visible(d) for d in DOCKS)
    assert not state.visible("left") and not state.visible("right")
    assert state.workspace == "focus"
    state.set_visible("footer", False)
    assert state.workspace == "custom" and not state.visible("footer")
    with pytest.raises(ValueError):
        state.apply_workspace("nope")
    with pytest.raises(ValueError):
        state.set_visible("nope", True)
    assert set(WORKSPACES["full"]) == set(PANELS)


def test_aliases_cover_the_right_docks():
    state = PanelState()
    state.set_visible("right", False)
    assert not state.visible("activity_log") and not state.visible("input") and state.visible("controls")
    state.set_visible("log", True)
    assert state.visible("activity_log") and not state.visible("right")
    state.set_visible("Activity Log", False)
    assert not state.visible("activity_log")


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
    assert "hidden" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "controls"}, player=ui)
    assert not ui.state.visible("controls")
    assert "shown" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "left", "visible": True}, player=ui)
    assert ui.state.visible("controls")
    assert "applied" in ui_layout.ui_layout({"mode": "workspace", "workspace": "coding"}, player=ui)
    assert not ui.state.visible("controls") and ui.state.visible("right")
    assert '"coding"' in ui_layout.ui_layout({"mode": "status"}, player=ui)
    assert "Unknown workspace" in ui_layout.ui_layout({"mode": "workspace", "workspace": "x"}, player=ui)
    assert "Unknown panel" in ui_layout.ui_layout({"mode": "toggle_panel", "panel": "x"}, player=ui)


def test_tool_toggle_panel_toggles_the_log():
    ui = _Ui()
    ui_layout.ui_layout({"mode": "toggle_panel", "panel": "activity_log"}, player=ui)
    assert not ui.state.visible("activity_log")
    ui_layout.ui_layout({"mode": "toggle_panel", "panel": "activity_log"}, player=ui)
    assert ui.state.visible("activity_log")


def test_tool_float_and_restore():
    ui = _Ui()
    assert "detached" in ui_layout.ui_layout({"mode": "float_panel", "panel": "controls", "floating": True}, player=ui)
    assert ui.floating["controls"]
    assert "docked again" in ui_layout.ui_layout({"mode": "float_panel", "panel": "controls", "floating": False}, player=ui)
    assert not ui.floating["controls"]
    ui_layout.ui_layout({"mode": "float_panel", "panel": "controls"}, player=ui)
    assert ui.floating["controls"]
    assert "Only these panels" in ui_layout.ui_layout({"mode": "float_panel", "panel": "footer"}, player=ui)
    assert "Unknown panel" in ui_layout.ui_layout({"mode": "float_panel", "panel": "nope"}, player=ui)
    assert "restored" in ui_layout.ui_layout({"mode": "restore_layout"}, player=ui)
    assert ui.restored == 1 and not ui.floating["controls"]


def test_layout_file_roundtrip_and_bad_files(tmp_path):
    path = tmp_path / "config" / "ui_layout.json"
    assert ui_panels.load_layout(path) is None
    ui_panels.save_layout(
        path, qt_state=b"\x00\x01state", geometry=b"geo", workspace="custom",
        panels={**WORKSPACES["full"], "activity_log": False}, floating={"controls": True},
    )
    data = ui_panels.load_layout(path)
    assert data["qt_state"] == b"\x00\x01state" and data["geometry"] == b"geo"
    assert data["panels"]["activity_log"] is False and data["floating"]["controls"] is True
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
    ui_layout.ui_layout({"mode": "toggle_panel", "panel": "right", "visible": False}, player=jarvis)
    real_ui.app.processEvents()
    assert not win._docks["activity_log"].isVisible() and not win._docks["input"].isVisible()
    assert jarvis.panel_status()["workspace"] == "custom"


def test_quantum_hud_draws_blueprint_and_uses_runtime_telemetry():
    from types import SimpleNamespace
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

    class Gauge:
        def __init__(self):
            self.value = None

        def set_value(self, pct, text):
            self.value = (pct, text)

    class Progress:
        value = None

        def setValue(self, value):
            self.value = value

    class Label:
        text = ""

        def setText(self, text):
            self.text = text

    fake_window = SimpleNamespace(
        get_hud_runtime=lambda: {
        "skills": {"active": 2, "total": 4},
        "task": {
            "status": "awaiting_confirmation",
            "completed": 1,
            "total": 4,
            "progress": 25,
        },
        },
        _gauge_skills=Gauge(),
        _gauge_task=Gauge(),
        _gauge_load=Gauge(),
        _task_runner_progress=Progress(),
        _task_runner_label=Label(),
    )
    ui_module.MainWindow._update_hud_runtime(fake_window)
    assert fake_window._gauge_skills.value == (50.0, "2/4")
    assert fake_window._gauge_task.value == (25, "1/4")
    assert fake_window._gauge_load.value == (0, "N/A")
    assert fake_window._task_runner_progress.value == 25
    assert fake_window._task_runner_label.text == (
        "TASK RUNNER: 25% - AWAITING CONFIRMATION"
    )


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


def test_docks_are_movable_closable_floatable_and_center_stays_central(real_ui):
    from PyQt6.QtWidgets import QDockWidget
    win = real_ui()._win
    for dock in win._docks.values():
        feats = dock.features()
        for flag in (QDockWidget.DockWidgetFeature.DockWidgetMovable,
                     QDockWidget.DockWidgetFeature.DockWidgetClosable,
                     QDockWidget.DockWidgetFeature.DockWidgetFloatable):
            assert feats & flag
    assert not isinstance(win.centralWidget(), QDockWidget)
    assert win.centralWidget().isAncestorOf(win._main_content_stack)
    assert win._main_content_stack.isAncestorOf(win.hud)
    assert all(not win.centralWidget().isAncestorOf(d) for d in win._docks.values())


def test_closing_with_x_updates_state_and_tool_reopens(real_ui):
    jarvis = real_ui()
    win = jarvis._win
    win._docks["activity_log"].close()
    real_ui.app.processEvents()
    assert not win._docks["activity_log"].isVisible()
    assert jarvis.panel_status()["panels"]["activity_log"] is False
    ui_layout.ui_layout({"mode": "toggle_panel", "panel": "activity_log"}, player=jarvis)
    real_ui.app.processEvents()
    assert win._docks["activity_log"].isVisible()
    assert jarvis.panel_status()["panels"]["activity_log"] is True


def test_center_expands_when_docks_close(real_ui):
    win = real_ui()._win
    before = win.centralWidget().width()
    for name in DOCKS:
        win._docks[name].close()
    real_ui.app.processEvents()
    assert win.centralWidget().width() > before
    assert win.centralWidget().isVisible()


def test_float_and_restore_layout(real_ui):
    from PyQt6.QtCore import Qt
    jarvis = real_ui()
    win = jarvis._win
    ui_layout.ui_layout({"mode": "float_panel", "panel": "controls", "floating": True}, player=jarvis)
    real_ui.app.processEvents()
    assert win._docks["controls"].isFloating() and win._docks["controls"].isVisible()
    assert jarvis.panel_status()["floating"]["controls"] is True
    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win._docks["activity_log"])
    win._docks["input"].close()
    real_ui.app.processEvents()
    ui_layout.ui_layout({"mode": "restore_layout"}, player=jarvis)
    real_ui.app.processEvents()
    assert all(d.isVisible() and not d.isFloating() for d in win._docks.values())
    assert win.dockWidgetArea(win._docks["controls"]) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert win.dockWidgetArea(win._docks["activity_log"]) == Qt.DockWidgetArea.RightDockWidgetArea
    assert win.dockWidgetArea(win._docks["input"]) == Qt.DockWidgetArea.RightDockWidgetArea
    assert jarvis.panel_status()["workspace"] == "full"


def test_focus_mode_hides_without_destroying_and_restores_exactly(real_ui):
    jarvis = real_ui()
    win = jarvis._win
    docks = dict(win._docks)
    win._docks["activity_log"].close()
    jarvis.float_panel("controls", True)
    real_ui.app.processEvents()
    before = _visible(win)
    jarvis.set_focus_mode(True)
    real_ui.app.processEvents()
    assert win._focus_mode and not any(win._docks[n].isVisible() for n in DOCKS)
    assert win._docks == docks and all(d.parent() is not None or d.isFloating() for d in docks.values())
    jarvis.set_focus_mode(False)
    real_ui.app.processEvents()
    assert _visible(win) == before
    assert not win._docks["activity_log"].isVisible()
    assert win._docks["controls"].isFloating() and win._docks["controls"].isVisible()


def test_focus_shortcut_toggles_twice(real_ui):
    win = real_ui()._win
    win.set_focus_mode(True)
    win.set_focus_mode(False)
    real_ui.app.processEvents()
    assert all(win._docks[n].isVisible() for n in DOCKS)


def test_layout_survives_restart(real_ui):
    from PyQt6.QtCore import Qt
    first = real_ui()
    win = first._win
    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, win._docks["activity_log"])
    win._docks["input"].close()
    first.float_panel("controls", True)
    real_ui.app.processEvents()
    win.close()
    assert real_ui.path.exists()

    second = real_ui()
    win2 = second._win
    assert win2.dockWidgetArea(win2._docks["activity_log"]) == Qt.DockWidgetArea.LeftDockWidgetArea
    # A closed input dock is never restored: without it the user cannot type.
    assert win2._docks["input"].isVisible()
    assert win2._docks["controls"].isFloating() and win2._docks["controls"].isVisible()
    assert second.panel_status()["panels"]["input"] is True


def test_closing_while_in_focus_saves_the_pre_focus_layout(real_ui):
    first = real_ui()
    first._win._docks["controls"].close()
    real_ui.app.processEvents()
    first.set_focus_mode(True)
    real_ui.app.processEvents()
    first._win.close()
    second = real_ui()
    assert second.panel_status()["panels"]["input"] is True
    assert second.panel_status()["panels"]["controls"] is False
    assert not second._win._focus_mode


def test_corrupt_or_floating_input_layout_falls_back_to_default_and_chat_request(real_ui):
    from PyQt6.QtCore import Qt
    # One window only: every extra real window makes the in-process Qt/WebEngine suite crash.
    ui_panels.save_layout(
        real_ui.path, qt_state=b"", panels={n: True for n in PANELS}, workspace="custom",
        floating={"input": True, "controls": True},
    )
    win = real_ui()._win
    assert all(d.isVisible() for d in win._docks.values())
    assert not win._docks["input"].isFloating() and not win._docks["controls"].isFloating()
    assert win.dockWidgetArea(win._docks["input"]) == Qt.DockWidgetArea.RightDockWidgetArea
    win.on_text_command = None
    opened = []
    win._show_gemini_chat = lambda: opened.append(True)
    win._input.setText("che tempo fa")
    win._send()
    assert not opened
    win._input.setText("apri la chat")
    win._send()
    assert opened == [True]


def test_layout_anomalies_and_chat_phrases():
    assert ui_panels.layout_anomalies({"floating": {"input": True}})
    assert not ui_panels.layout_anomalies({"floating": {"controls": True}})
    for text in ("apri la chat", "Jarvis parliamo", "open the chat", "let's talk"):
        assert ui_panels.wants_chat(text), text
    for text in ("che tempo fa", "chatgpt", "una sedia"):
        assert not ui_panels.wants_chat(text), text

import os
import sys
import time

import pytest

from actions import viewer_3d
from core.viewer3d import build_call

# Real QtWebEngine pages crash natively (stack overflow/access violation) on the windows-latest runner once the
# docked window is built; they pass locally, so CI skips them rather than reporting a runner-only crash.
needs_local_gpu_stack = pytest.mark.skipif(bool(os.environ.get("CI")), reason="QtWebEngine crashes on the CI runner")


def test_build_call_validates_and_serialises():
    assert build_call("flyTo", [41.9, 12.5]) == ("flyTo", "[41.9, 12.5]")
    assert build_call("addMarker", ["10", 20, "x" * 100])[1].count("x") == 60
    assert build_call("clearMarkers", []) == ("clearMarkers", "[]")
    assert build_call("setClipping", ["x", 0.5]) == ("setClipping", '["x", 0.5]')
    assert build_call("applyPhysics", [" DROP "]) == ("applyPhysics", '["drop"]')
    assert build_call("setHudState", ["listening", "#00ff88", 0.9, 1.1, 8, 0.3])[0] == "setHudState"
    for bad in (
        ("flyTo", [91, 0]), ("flyTo", [0, 181]), ("flyTo", ["a", 0]),
        ("flyTo", [True, 0]), ("flyTo", [1]), ("spin", [1]),
        ("eval", []), ("document.write", ["x"]),
        ("setHudState", ["unknown", "#00ff88", 0.9, 1.1, 8, 0.3]),
        ("setHudState", ["idle", "blue", 0.9, 1.1, 8, 0.3]),
        ("setClipping", ["w", 0.5]), ("setClipping", ["x", 2]),
        ("applyPhysics", ["arbitrary"]), ("applyPhysics", [True]),
    ):
        with pytest.raises(ValueError):
            build_call(*bad)


class _Ui:
    def __init__(self):
        self.calls = []

    def viewer3d_show(self, visible):
        self.calls.append(("show", visible))

    def viewer3d_call(self, function, args):
        build_call(function, args)
        self.calls.append((function, args))


def test_tool_routes_modes_and_reports_invalid_input():
    ui = _Ui()
    assert "shown" in viewer_3d.viewer_3d({"mode": "show"}, player=ui)
    assert "turning" in viewer_3d.viewer_3d({"mode": "fly_to", "lat": 1, "lon": 2}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "fly_to", "lat": 99, "lon": 2}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "fly_to"}, player=ui)
    assert "Unknown mode" in viewer_3d.viewer_3d({"mode": "x"}, player=ui)
    assert "not available" in viewer_3d.viewer_3d({"mode": "show"}, player=None)
    assert ui.calls == [("show", True), ("flyTo", [1, 2])]
    assert "Clipping enabled" in viewer_3d.viewer_3d({"mode": "set_clipping", "axis": "y"}, player=ui)
    assert ui.calls[-1] == ("setClipping", ["y", 0.5])
    assert "Invalid request" in viewer_3d.viewer_3d({"mode": "set_clipping", "axis": "invalid"}, player=ui)
    assert "Physics drop" in viewer_3d.viewer_3d(
        {"mode": "apply_physics", "physics_mode": "DROP"}, player=ui
    )
    assert ui.calls[-1] == ("applyPhysics", ["drop"])
    assert "Invalid request" in viewer_3d.viewer_3d(
        {"mode": "apply_physics", "physics_mode": "arbitrary"}, player=ui
    )
    assert viewer_3d.TOOL["risk_class"] == "read"


@needs_local_gpu_stack
def test_real_page_physics_pc_and_explode_interactions():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --use-gl=angle --use-angle=swiftshader")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    try:
        viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "ready")
        state = _poll_state(app, win, lambda s: s["physics"]["status"] == "ready")
        assert state["model"]["name"] == "cad/pc.glb"

        viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1)
        assert any(distance > 0.1 for distance in state["model"]["moved"])
        viewer_3d.viewer_3d(
            {"mode": "apply_physics", "physics_mode": "drop"}, player=jarvis
        )
        state = _poll_state(
            app, win,
            lambda s: s["physics"]["active"] and s["model"]["explode"] == 0,
        )
        assert state["physics"]["mode"] == "drop"
        assert all(distance < 0.001 for distance in state["model"]["moved"])
        state = _poll_state(
            app, win,
            lambda s: s["physics"]["active"]
            and s["physics"]["bottom"] is not None
            and abs(s["physics"]["bottom"]) <= 0.03
            and abs(s["physics"]["velocityY"]) < 0.1,
        )
        assert abs(state["physics"]["bottom"]) <= 0.03

        viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
        state = _poll_state(
            app, win,
            lambda s: not s["physics"]["active"] and s["model"]["explode"] == 1,
        )
        assert any(distance > 0.1 for distance in state["model"]["moved"])
        viewer_3d.viewer_3d(
            {"mode": "apply_physics", "physics_mode": "impulse"}, player=jarvis
        )
        state = _poll_state(
            app, win,
            lambda s: s["physics"]["active"] and s["physics"]["velocityY"] > 0.1,
        )
        assert state["physics"]["mode"] == "impulse"
        assert all(distance < 0.001 for distance in state["model"]["moved"])

        viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)
        state = _poll_state(app, win, lambda s: not s["physics"]["active"])
        assert state["model"]["status"] == "none"
    finally:
        win._layout_timer.stop()
        win.close()


@needs_local_gpu_stack
def test_real_page_physics_apple_drop():
    source = os.environ.get("JARVIS_TEST_APPLE_GLB")
    if not source or not os.path.isfile(source):
        pytest.skip("set JARVIS_TEST_APPLE_GLB to the apple GLB test asset")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --use-gl=angle --use-angle=swiftshader")
    import shutil
    import tempfile
    from pathlib import Path
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module
    from core.viewer3d import MODELS_DIR

    MODELS_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="pytest_apple_", suffix=".glb", dir=MODELS_DIR, delete=False
    ) as temporary:
        target = Path(temporary.name)
    shutil.copyfile(source, target)
    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    try:
        viewer_3d.viewer_3d(
            {"mode": "load_model", "model": target.name}, player=jarvis
        )
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "ready")
        assert state["model"]["name"] == target.name
        _poll_state(app, win, lambda s: s["physics"]["status"] == "ready")
        viewer_3d.viewer_3d(
            {"mode": "apply_physics", "physics_mode": "drop"}, player=jarvis
        )
        state = _poll_state(
            app, win,
            lambda s: s["physics"]["active"]
            and s["physics"]["bottom"] is not None
            and abs(s["physics"]["bottom"]) <= 0.03
            and abs(s["physics"]["velocityY"]) < 0.1,
        )
        assert state["physics"]["mode"] == "drop"
        assert abs(state["physics"]["bottom"]) <= 0.03
    finally:
        win._layout_timer.stop()
        win.close()
        target.unlink(missing_ok=True)


@needs_local_gpu_stack
def test_real_page_loads_and_receives_commands():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --use-gl=angle --use-angle=swiftshader")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win

    viewer_3d.viewer_3d({"mode": "show"}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "add_marker", "lat": 41.9, "lon": 12.5, "label": "Roma"}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "fly_to", "lat": 41.9, "lon": 12.5}, player=jarvis)

    result = {}
    deadline = time.time() + 40
    while time.time() < deadline and "state" not in result:
        app.processEvents()
        if win._viewer3d_loaded:
            win._viewer3d.page().runJavaScript(
                "window.jarvisViewer ? JSON.stringify(window.jarvisViewer.getState()) : null",
                lambda value: result.__setitem__("state", value),
            )
            t = time.time() + 1
            while time.time() < t and "state" not in result:
                app.processEvents()
            if result.get("state") is None:
                result.pop("state", None)
        time.sleep(0.05)

    assert win._viewer3d_loaded, "page failed to load"
    import json
    state = json.loads(result["state"])
    assert state["ready"] and state["flying"]
    assert state["markers"] == [{"lat": 41.9, "lon": 12.5, "label": "Roma"}]


def test_fly_to_and_recon_bring_viewer_to_front():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    assert win._hud_cam_stack.currentWidget() is win.hud

    viewer_3d.viewer_3d({"mode": "fly_to", "lat": 1, "lon": 2}, player=jarvis)
    app.processEvents()
    assert win._hud_cam_stack.currentWidget() is win._viewer3d

    win.show_viewer3d(False)
    assert win._hud_cam_stack.currentWidget() is win.hud
    jarvis.apply_workspace("recon")
    app.processEvents()
    assert win._hud_cam_stack.currentWidget() is win._viewer3d


@needs_local_gpu_stack
def test_real_page_model_events_restore_viewer_and_report_load_errors():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    win.show_viewer3d(False)
    win._viewer3d_on_event("modelLoaded", {"id": "apple-test", "name": "apple.glb"})
    app.processEvents()
    assert win._hud_cam_stack.currentWidget() is win._viewer3d
    assert win.hud._projection_status == "MODEL READY / APPLE-TEST"

    win._viewer3d_on_event(
        "commandError", {"command": "loadModel", "message": "model not found"}
    )
    assert win._hud_cam_stack.currentWidget() is win.hud
    assert win.hud._projection_status.startswith("MODEL LOAD FAILED")

    win._layout_timer.stop()
    win.close()
def test_parse_states_and_fetch_with_fake_opener():
    import io, json
    from core import viewer3d as v

    payload = {"states": [
        ["a", "ITA123 ", "IT", 0, 0, 12.5, 41.9, 10000.0, False],
        ["b", "GND1", "IT", 0, 0, 12.0, 41.0, 0, True],
        ["c", "NOPOS", "IT", 0, 0, None, None, 0, False],
    ]}
    assert v.parse_states(payload) == [[41.9, 12.5, "ITA123", 10000.0]]
    assert len(v.parse_states({"states": [["x", "", "", 0, 0, 1, 2, 3, False]] * 1000})) == v.MAX_FLIGHTS

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    seen = {}
    def opener(req, timeout):
        seen["url"] = req.full_url
        return Resp(json.dumps(payload).encode())
    assert v.fetch_flights("usa", opener=opener)[0][2] == "ITA123"
    assert "lamin=24.0" in seen["url"]
    with pytest.raises(ValueError):
        v.fetch_flights("mars", opener=opener)

    def boom(req, timeout):
        raise OSError("offline")
    with pytest.raises(RuntimeError):
        v.fetch_flights("europe", opener=boom)


def test_set_flights_validation():
    from core.viewer3d import build_call
    fn, args = build_call("setFlights", [[[1, 2, "X", 5]]])
    assert fn == "setFlights" and '"X"' in args
    with pytest.raises(ValueError):
        build_call("setFlights", [[[100, 2, "X"]]])
    with pytest.raises(ValueError):
        build_call("setFlights", [[[1, 2]]])
    assert build_call("clearFlights", []) == ("clearFlights", "[]")


def test_tool_load_live_flights_runs_off_ui(monkeypatch):
    calls = []
    class P:
        def viewer3d_call(self, f, a): calls.append((f, a))
        def viewer3d_show(self, v): pass
    monkeypatch.setattr(viewer_3d, "fetch_flights", lambda region: [[1.0, 2.0, "AB", 0]])
    out = viewer_3d.viewer_3d({"mode": "load_live_flights", "region": "usa"}, player=P())
    assert "1 live flights" in out and calls == [("setFlights", [[[1.0, 2.0, "AB", 0]]])]
    def fail(region): raise RuntimeError("OpenSky not reachable: x")
    monkeypatch.setattr(viewer_3d, "fetch_flights", fail)
    assert "not reachable" in viewer_3d.viewer_3d({"mode": "load_live_flights"}, player=P())


def test_model_file_validation(tmp_path):
    from core.viewer3d import model_file
    from tests.glb_helper import make_glb
    make_glb(tmp_path / "ok.glb")
    assert model_file("ok.glb", tmp_path).name == "ok.glb"
    for bad in ("../ok.glb", "sub/ok.glb", "ok.txt", "", "C:\\x.glb", "missing.glb", "..\\ok.glb"):
        with pytest.raises(ValueError):
            model_file(bad, tmp_path)
    big = tmp_path / "big.glb"
    big.write_bytes(b"x")
    import core.viewer3d as v
    old, v.MAX_MODEL_BYTES = v.MAX_MODEL_BYTES, 0
    try:
        with pytest.raises(ValueError):
            model_file("big.glb", tmp_path)
    finally:
        v.MAX_MODEL_BYTES = old
    assert build_call("loadModel", ["ok.glb"]) == ("loadModel", '["ok.glb"]')
    with pytest.raises(ValueError):
        build_call("loadModel", ["../x.glb"])


def _poll_state(app, win, until, timeout=40):
    import json
    deadline, state = time.time() + timeout, None
    while time.time() < deadline:
        box = {}
        if win._viewer3d_loaded:
            win._viewer3d.page().runJavaScript(
                "JSON.stringify(window.jarvisViewer.getState())",
                lambda v: box.__setitem__("s", v),
            )
            t = time.time() + 1
            while time.time() < t and "s" not in box:
                app.processEvents()
            if box.get("s"):
                state = json.loads(box["s"])
                if until(state):
                    return state
        app.processEvents()
        time.sleep(0.1)
    return state


@needs_local_gpu_stack
def test_real_page_loads_glb_model():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module
    from core.viewer3d import MODELS_DIR
    from tests.glb_helper import make_glb

    MODELS_DIR.mkdir(exist_ok=True)
    path = MODELS_DIR / "pytest_model.glb"
    make_glb(path)
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        jarvis = ui_module.JarvisUI("")
        win = jarvis._win
        out = viewer_3d.viewer_3d({"mode": "load_model", "model": "pytest_model.glb"}, player=jarvis)
        assert "loaded" in out
        state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
        assert state["model"]["status"] == "ready", state["model"]
        assert state["model"]["nodes"] == ["part_a", "part_b"]
        assert win._hud_cam_stack.currentWidget() is win._viewer3d

        viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "none")
        assert state["model"]["status"] == "none"
        assert "not found" in viewer_3d.viewer_3d({"mode": "load_model", "model": "nope.glb"}, player=jarvis) \
            or "Invalid" in viewer_3d.viewer_3d({"mode": "load_model", "model": "nope.glb"}, player=jarvis)
    finally:
        path.unlink(missing_ok=True)


@needs_local_gpu_stack
def test_real_page_clips_pc_cad_during_mouse_rotation():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    try:
        win.resize(900, 700)
        win.show()
        viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
        assert state["model"]["status"] == "ready", state["model"]
        if not state["webgl"]:
            pytest.skip("WebGL is not available in this environment")

        viewer_3d.viewer_3d({"mode": "set_clipping", "axis": "x"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["clipping"]["axis"] == "x")
        assert state["clipping"]["clipped"] > 0
        assert state["clipping"]["caps"] == 1
        assert state["spin"] is False

        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest
        target = win._viewer3d.focusProxy() or win._viewer3d
        before = state["controls"]["azimuth"]
        start = QPoint(target.width() // 2, target.height() // 2)
        QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for step in range(1, 21):
            QTest.mouseMove(target, start + QPoint(step * 8, 0))
            app.processEvents()
        QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(160, 0))
        state = _poll_state(app, win, lambda s: abs(s["controls"]["azimuth"] - before) > 0.1)
        assert state["clipping"]["caps"] == 1
        assert state["model"]["shaderError"] == ""
        viewer_3d.viewer_3d({"mode": "spin", "spin": True}, player=jarvis)
        assert _poll_state(app, win, lambda s: True)["spin"] is False
        for style in ("realistic", "blueprint", "hologram"):
            viewer_3d.viewer_3d({"mode": "set_material_style", "style": style}, player=jarvis)
            state = _poll_state(app, win, lambda s: s["model"]["style"] == style)
            assert state["clipping"]["caps"] == 1
            assert state["model"]["shaderError"] == ""

        viewer_3d.viewer_3d({"mode": "set_clipping", "axis": "off"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["clipping"]["axis"] == "")
        assert state["clipping"]["clipped"] == 0
    finally:
        win._layout_timer.stop()
        win.close()


def test_pc_cad_has_pbr_materials_and_cylinders(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    from core.make_pc_cad import make_pc_cad

    scene = trimesh.load(make_pc_cad(tmp_path))
    mats = {n: g.visual.material for n, g in scene.geometry.items()}
    assert mats["case"].metallicFactor == 1.0
    assert mats["motherboard"].roughnessFactor == pytest.approx(0.2)
    assert list(mats["ram_1"].baseColorFactor[:3]) == [212, 175, 55]
    # a fan is a disc (cylinder): its bounding box is square in y/z and thin along x
    ext = scene.geometry["fan"].extents
    assert abs(ext[1] - ext[2]) < 1e-6 and ext[0] < ext[1]


def test_teaching_sequence_calls_tool_in_order():
    pytest.importorskip("trimesh")  # cad/pc.glb is built on first use and needs trimesh
    calls = []

    class _Ui:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append((name, a))

    ui = _Ui()
    for args in ({"mode": "load_model", "model": "cad/pc.glb"}, {"mode": "explode_model", "on": True},
                 {"mode": "highlight_part", "part": "cpu"}):
        viewer_3d.viewer_3d(args, player=ui)
    assert len(calls) >= 3


@needs_local_gpu_stack
def test_real_page_realistic_pbr_teaching_and_generated_label():
    trimesh = pytest.importorskip("trimesh")
    from core.make_pc_cad import make_pc_cad
    from core.viewer3d import MODELS_DIR
    make_pc_cad()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    MODELS_DIR.mkdir(exist_ok=True)
    gen = MODELS_DIR / "image-ferrari-abc123.glb"
    gen.write_bytes(trimesh.creation.box().export(file_type="glb"))
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        jarvis = ui_module.JarvisUI("")
        win = jarvis._win
        viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
        assert state["model"]["status"] == "ready", state["model"]
        viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
        viewer_3d.viewer_3d({"mode": "highlight_part", "part": "cpu"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1 and s["model"]["glowing"] > 0)
        assert state["model"]["glowing"] > 0 and state["model"]["highlight"] == "cpu", state["model"]

        viewer_3d.viewer_3d({"mode": "set_material_style", "style": "realistic"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["style"] == "realistic" and s["look"]["shadows"])
        look = state["look"]
        assert look["shadows"] and look["shadowFloor"] and look["shadowCasters"] >= 9, look
        assert look["toneMapping"] != 0, look
        state = _poll_state(app, win, lambda s: s["look"]["envLoaded"] or s["look"]["envError"], timeout=20)
        assert state["look"]["envLoaded"] and state["look"]["environment"], state["look"]

        viewer_3d.viewer_3d({"mode": "set_material_style", "style": "blueprint"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["style"] == "blueprint")
        assert not state["look"]["shadows"] and not state["look"]["environment"], state["look"]

        viewer_3d.viewer_3d({"mode": "load_model", "model": "image-ferrari-abc123.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["name"].startswith("image-ferrari") and s["model"]["status"] == "ready")
        assert state["model"]["label"] == "Ferrari", state["model"]
        viewer_3d.viewer_3d({"mode": "spin", "spin": False}, player=jarvis)
        win._viewer3d.page().runJavaScript(
            "(() => { const r = document.getElementById('c').getBoundingClientRect();"
            "document.getElementById('c').dispatchEvent(new MouseEvent('mousemove',"
            "{clientX: r.left + r.width / 2, clientY: r.top + r.height / 2})); })()"
        )
        state = _poll_state(app, win, lambda s: s["model"]["hover"]["name"] != "")
        assert state["model"]["hover"]["name"] == "Ferrari", state["model"]["hover"]
        viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)
    finally:
        gen.unlink(missing_ok=True)


@needs_local_gpu_stack
def test_real_page_flat_and_toon_styles():
    pytest.importorskip("trimesh")
    from core.make_pc_cad import make_pc_cad
    make_pc_cad()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    viewer_3d.viewer_3d({"mode": "set_material_style", "style": "toon"}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
    assert state["model"]["status"] == "ready" and state["model"]["style"] == "toon", state["model"]
    assert set(state["model"]["materials"]) == {"MeshToonMaterial"}, state["model"]["materials"]
    viewer_3d.viewer_3d({"mode": "set_material_style", "style": "flat"}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["style"] == "flat")
    assert set(state["model"]["materials"]) == {"MeshBasicMaterial"}, state["model"]["materials"]
    viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)


@needs_local_gpu_stack
def test_real_page_explode_and_highlight():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module
    from core.viewer3d import MODELS_DIR
    from tests.glb_helper import make_glb

    MODELS_DIR.mkdir(exist_ok=True)
    path = MODELS_DIR / "pytest_parts.glb"
    make_glb(path)
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        jarvis = ui_module.JarvisUI("")
        win = jarvis._win
        viewer_3d.viewer_3d({"mode": "load_model", "model": "pytest_parts.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "ready")
        assert state["model"]["parts"] == 2 and state["model"]["moved"] == [0, 0]

        assert "exploded" in viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1)
        assert state["model"]["explode"] == 1 and all(d > 0.1 for d in state["model"]["moved"]), state["model"]

        viewer_3d.viewer_3d({"mode": "highlight_part", "part": "part_a"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["highlight"] == "part_a")
        assert state["model"]["highlight"] == "part_a" and state["model"]["glowing"] == 1
        viewer_3d.viewer_3d({"mode": "highlight_part", "part": ""}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["highlight"] == "")
        assert state["model"]["glowing"] == 0

        viewer_3d.viewer_3d({"mode": "explode_model", "on": False}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["explode"] == 0)
        assert all(d < 0.001 for d in state["model"]["moved"]), state["model"]
    finally:
        path.unlink(missing_ok=True)


def test_explode_highlight_validation():
    assert build_call("explodeModel", [True]) == ("explodeModel", "[true]")
    assert build_call("highlightPart", [" turbine "]) == ("highlightPart", '["turbine"]')
    with pytest.raises(ValueError):
        build_call("explodeModel", ["yes"])
    with pytest.raises(ValueError):
        build_call("highlightPart", [5])


@needs_local_gpu_stack
def test_real_page_hologram_shader_and_toggle():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module
    from core.viewer3d import MODELS_DIR
    from tests.glb_helper import make_glb

    MODELS_DIR.mkdir(exist_ok=True)
    path = MODELS_DIR / "pytest_holo.glb"
    make_glb(path)
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        jarvis = ui_module.JarvisUI("")
        win = jarvis._win
        viewer_3d.viewer_3d({"mode": "load_model", "model": "pytest_holo.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "ready")
        assert state["model"]["hologram"] is True
        if state["webgl"]:
            time.sleep(1.5)  # let several frames compile and draw the shader
            state = _poll_state(app, win, lambda s: True)
            assert state["model"]["shaderError"] == ""

        viewer_3d.viewer_3d({"mode": "highlight_part", "part": "part_b"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["glowing"] == 1)
        assert state["model"]["glowing"] == 1

        viewer_3d.viewer_3d({"mode": "set_hologram", "on": False}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["hologram"] is False)
        assert state["model"]["hologram"] is False and state["model"]["glowing"] == 1
        viewer_3d.viewer_3d({"mode": "set_hologram", "on": True}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["hologram"] is True)
        assert state["model"]["hologram"] is True and state["model"]["glowing"] == 1
        assert state["model"]["shaderError"] == ""
    finally:
        path.unlink(missing_ok=True)


def test_material_style_and_part_info_validation():
    assert build_call("setMaterialStyle", [" Blueprint "]) == ("setMaterialStyle", '["blueprint"]')
    for bad in ("neon", "", 3, None):
        with pytest.raises(ValueError):
            build_call("setMaterialStyle", [bad])
    func, raw = build_call("setPartInfo", [{" fan ": "x" * 500, "": "skip", "gpu": 7}])
    import json
    info = json.loads(raw)[0]
    assert func == "setPartInfo" and list(info) == ["fan", "gpu"] and len(info["fan"]) == 300 and info["gpu"] == "7"
    for bad in ("text", ["a"], None):
        with pytest.raises(ValueError):
            build_call("setPartInfo", [bad])


def test_tool_style_part_info_and_list_parts(tmp_path, monkeypatch):
    import core.viewer3d as core_viewer
    from tests.glb_helper import make_glb

    make_glb(tmp_path / "m.glb")
    monkeypatch.setattr(core_viewer, "MODELS_DIR", tmp_path)
    ui = _Ui()
    assert "blueprint" in viewer_3d.viewer_3d({"mode": "set_material_style", "style": "Blueprint"}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "set_material_style", "style": "neon"}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "set_material_style"}, player=ui)
    assert "1 part" in viewer_3d.viewer_3d(
        {"mode": "set_part_info", "part_info": '{"part_a": "Scheda video"}'}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "set_part_info", "part_info": "not json"}, player=ui)
    assert "Invalid" in viewer_3d.viewer_3d({"mode": "set_part_info", "part_info": "{}"}, player=ui)
    assert viewer_3d.viewer_3d({"mode": "list_parts", "model": "m.glb"}, player=ui) == "Parts: part_a, part_b"
    assert ui.calls == [("setMaterialStyle", ["blueprint"]), ("setPartInfo", [{"part_a": "Scheda video"}])]
    assert "style" in viewer_3d.TOOL["parameters"]["properties"]


def test_part_names_sanitised_like_three(tmp_path):
    import json
    import struct
    from core.viewer3d import part_names

    doc = json.dumps({"asset": {"version": "2.0"}, "nodes": [{"name": "Fan blade.01"}, {"name": "a[b]"}, {}]}).encode()
    doc += b" " * (-len(doc) % 4)
    blob = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(doc)) + struct.pack("<II", len(doc), 0x4E4F534A) + doc
    (tmp_path / "n.glb").write_bytes(blob)
    assert part_names(tmp_path / "n.glb") == ["Fan_blade01", "ab"]


@needs_local_gpu_stack
def test_real_page_blueprint_style_and_hover_tooltip():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module
    from core.viewer3d import MODELS_DIR
    from tests.glb_helper import make_glb

    MODELS_DIR.mkdir(exist_ok=True)
    path = MODELS_DIR / "pytest_hover.glb"
    make_glb(path)

    def run_js(win, app, script):
        win._viewer3d.page().runJavaScript(script)
        for _ in range(5):
            app.processEvents()

    # Screen position of a point of part_a (model is 1.6 units wide, camera at z=4.2, fov 45).
    move = """
    (() => {
      const r = document.getElementById('c').getBoundingClientRect();
      const half = 4.2 * Math.tan(22.5 * Math.PI / 180);
      const x = r.left + r.width * (0.5 + (%s) / (half * r.width / r.height) / 2);
      const y = r.top + r.height * (0.5 - (%s) / half / 2);
      for (let i = 0; i < %d; i++)
        document.getElementById('c').dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y}));
    })()
    """
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        jarvis = ui_module.JarvisUI("")
        win = jarvis._win
        viewer_3d.viewer_3d({"mode": "load_model", "model": "pytest_hover.glb"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "ready")
        assert state["model"]["style"] == "hologram" and state["model"]["edges"] == 0

        viewer_3d.viewer_3d({"mode": "set_material_style", "style": "blueprint"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["style"] == "blueprint")
        assert state["model"]["hologram"] is False and state["model"]["edges"] == 2
        assert state["model"]["meshColors"] == ["0055ff", "0055ff"], state["model"]
        if state["webgl"]:
            time.sleep(0.5)
            assert _poll_state(app, win, lambda s: True)["model"]["shaderError"] == ""

        viewer_3d.viewer_3d({"mode": "spin", "spin": False}, player=jarvis)
        viewer_3d.viewer_3d({"mode": "set_part_info", "part_info": {"part_a": "Scheda video: calcoli grafici"}}, player=jarvis)
        # centroid of part_a's triangle in world units (see make_glb): about (-0.62, -0.09)
        run_js(win, app, move % ("-0.62", "-0.09", 1))
        state = _poll_state(app, win, lambda s: s["model"]["hover"]["name"] == "part_a")
        hover = state["model"]["hover"]
        assert hover == {**hover, "name": "part_a", "text": "Scheda video: calcoli grafici", "visible": True}, hover
        # the same hover reaches the Python side (tool hovered_part)
        deadline = time.time() + 5
        while time.time() < deadline and jarvis.viewer3d_hover().get("name") != "part_a":
            app.processEvents()
        assert jarvis.viewer3d_hover() == {"name": "part_a", "text": "Scheda video: calcoli grafici"}
        said = viewer_3d.viewer_3d({"mode": "hovered_part"}, player=jarvis)
        assert "part_a" in said and "Scheda video" in said, said

        # part_b has no description: tooltip shows just the name
        run_js(win, app, move % ("0.44", "-0.09", 1))
        state = _poll_state(app, win, lambda s: s["model"]["hover"]["name"] == "part_b")
        assert state["model"]["hover"]["text"] == "" and state["model"]["hover"]["visible"] is True

        # empty space hides the tooltip
        run_js(win, app, move % ("0", "1.4", 1))
        state = _poll_state(app, win, lambda s: not s["model"]["hover"]["visible"])
        assert state["model"]["hover"]["name"] == ""

        # throttle: 300 mousemove events in one task cost at most a handful of raycasts
        before = state["model"]["hover"]["rays"]
        run_js(win, app, move % ("-0.62", "-0.09", 300))
        state = _poll_state(app, win, lambda s: s["model"]["hover"]["visible"])
        assert state["model"]["hover"]["rays"] - before <= 4, state["model"]["hover"]

        viewer_3d.viewer_3d({"mode": "set_material_style", "style": "realistic"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["style"] == "realistic")
        assert state["model"]["edges"] == 0 and state["model"]["meshColors"] != ["0055ff", "0055ff"]
        viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)
        state = _poll_state(app, win, lambda s: s["model"]["status"] == "none")
        assert state["model"]["partInfo"] == 0 and state["model"]["hover"]["visible"] is False
    finally:
        path.unlink(missing_ok=True)


# Each spoken request, the tool call the ologramma skill tells the LLM to make, and the JS call.
VOICE_CASES = [
    ("metti in blueprint", {"mode": "set_material_style", "style": "blueprint"}, ("setMaterialStyle", ["blueprint"])),
    ("smontalo", {"mode": "explode_model", "on": True}, ("explodeModel", [True])),
    ("mostra texture", {"mode": "set_material_style", "style": "realistic"}, ("setMaterialStyle", ["realistic"])),
    ("torna all'ologramma", {"mode": "set_material_style", "style": "hologram"}, ("setMaterialStyle", ["hologram"])),
    ("spiega un PC", {"mode": "load_model", "model": "cad/pc.glb"}, ("loadModel", ["cad/pc.glb"])),
]


@pytest.mark.parametrize("phrase,call,expected", VOICE_CASES, ids=[c[0] for c in VOICE_CASES])
def test_simulated_llm_voice_commands_reach_the_viewer(phrase, call, expected):
    from pathlib import Path
    from core.tool_router import ToolRouter
    # 1. the router sends the viewer_3d schema to the LLM for this phrase
    declared = [{"name": "viewer_3d"}, {"name": "weather_report"}, {"name": "reminder"}]
    assert "viewer_3d" in {d["name"] for d in ToolRouter().select(phrase, declared)}
    # 2. the skill names the exact mode the LLM must use for the request
    skill = (Path(__file__).resolve().parents[1] / "skills" / "ologramma" / "SKILL.md").read_text(encoding="utf-8")
    assert f"mode={call['mode']}" in skill or f"`{call['mode']}`" in skill
    if "style" in call:
        assert f"style={call['style']}" in skill
    if "model" in call:
        assert call["model"] in skill
    # 3. the LLM's function call, executed by the real tool, yields the expected viewer call
    if call["mode"] == "load_model":
        pytest.importorskip("trimesh")
        from core.make_pc_cad import make_pc_cad
        make_pc_cad()
    ui = _Ui()
    out = viewer_3d.viewer_3d(dict(call), player=ui)
    assert "Invalid" not in out and "Unknown" not in out, out
    assert ui.calls == [expected]


def test_pc_cad_model_has_named_parts(tmp_path):
    pytest.importorskip("trimesh")
    from core.make_pc_cad import make_pc_cad
    from core.viewer3d import part_names
    path = make_pc_cad(tmp_path)
    assert path.name == "pc.glb" and path.read_bytes()[:4] == b"glTF"
    assert {"case", "motherboard", "cpu", "ram_1", "ram_2", "gpu", "psu"} <= set(part_names(path))


@needs_local_gpu_stack
def test_real_page_pc_cad_explodes():
    pytest.importorskip("trimesh")
    from core.make_pc_cad import make_pc_cad
    make_pc_cad()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/pc.glb"}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
    assert state["model"]["status"] == "ready", state["model"]
    assert state["model"]["parts"] >= 7, state["model"]
    viewer_3d.viewer_3d({"mode": "spin", "spin": False}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1)
    assert sum(1 for d in state["model"]["moved"] if d > 0.1) >= 5, state["model"]["moved"]
    viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)

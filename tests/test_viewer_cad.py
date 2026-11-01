import os
import sys
import time

import pytest

from actions import viewer_3d
from core.viewer3d import build_call
from tests.test_viewer3d import _Ui, _poll_state, needs_local_gpu_stack


def test_cad_model_names_and_listing(tmp_path):
    from core.viewer3d import list_models, model_file
    (tmp_path / "cad").mkdir()
    (tmp_path / "cad" / "engine.glb").write_bytes(b"glTF")
    (tmp_path / "cad" / "pc.glb").write_bytes(b"glTF")
    (tmp_path / "chair.glb").write_bytes(b"glTF")
    assert model_file("cad/engine.glb", base=tmp_path).name == "engine.glb"
    assert build_call("loadModel", ["cad/engine.glb"]) == ("loadModel", '["cad/engine.glb"]')
    assert list_models(tmp_path) == {"generated": ["chair.glb"], "cad": ["cad/engine.glb", "cad/pc.glb"],
                                     "downloads": []}
    for bad in ("cad/../chair.glb", "cad/sub/x.glb", "other/x.glb", "/cad/x.glb", "cad\\x.glb"):
        with pytest.raises(ValueError):
            build_call("loadModel", [bad])
        with pytest.raises(ValueError):
            model_file(bad, base=tmp_path)


def test_sanitize_hover_accepts_only_strings():
    from core.viewer3d import sanitize_hover
    assert sanitize_hover(" fan ", "cools") == {"name": "fan", "text": "cools"}
    assert len(sanitize_hover("x" * 200, "")["name"]) == 60
    assert sanitize_hover(5, "") is None and sanitize_hover("a", None) is None


def test_viewer_navigation_only_allows_local_viewer_folder(tmp_path):
    from core.viewer3d import is_viewer_url_allowed
    base = tmp_path / "assets" / "viewer3d"
    ok = (base / "index.html").as_uri()
    assert is_viewer_url_allowed(ok, base)
    assert is_viewer_url_allowed((base / "models" / "a b.glb").as_uri(), base)
    assert not is_viewer_url_allowed((tmp_path / "secret.txt").as_uri(), base)
    assert not is_viewer_url_allowed(base.as_uri() + "/../secret.txt", base)
    assert not is_viewer_url_allowed("https://example.com/", base)
    assert not is_viewer_url_allowed("javascript:alert(1)", base)


class _HoverUi(_Ui):
    def __init__(self, hover):
        super().__init__()
        self._hover = hover

    def viewer3d_hover(self):
        return self._hover


def test_tool_hovered_part_and_list_models():
    said = viewer_3d.viewer_3d({"mode": "hovered_part"}, player=_HoverUi({"name": "Fan", "text": "cools the card"}))
    assert said == "The user is looking at: Fan - cools the card"
    assert "no description" in viewer_3d.viewer_3d({"mode": "hovered_part"}, player=_HoverUi({"name": "Parte 2", "text": ""}))
    assert "not over any part" in viewer_3d.viewer_3d({"mode": "hovered_part"}, player=_HoverUi({"name": "", "text": ""}))
    assert "CAD" in viewer_3d.viewer_3d({"mode": "list_models"}, player=_Ui())


def test_download_cad_models_verifies_signature_and_checksum(tmp_path):
    import hashlib
    from core.cad_models import download_cad_models
    good = b"glTF" + b"0" * 20
    catalog = {
        "ok.glb": {"url": "u1", "sha256": hashlib.sha256(good).hexdigest()},
        "bad_sum.glb": {"url": "u2", "sha256": "0" * 64},
        "not_glb.glb": {"url": "u3", "sha256": "0" * 64},
    }
    blobs = {"u1": good, "u2": good, "u3": b"<html>"}
    out = download_cad_models(tmp_path, fetch=blobs.__getitem__, catalog=catalog)
    assert out["ok.glb"].startswith("downloaded")
    assert "mismatch" in out["bad_sum.glb"] and "not a binary glTF" in out["not_glb.glb"]
    assert (tmp_path / "ok.glb").is_file() and not (tmp_path / "bad_sum.glb").exists()
    again = download_cad_models(tmp_path, fetch=blobs.__getitem__, catalog={"ok.glb": catalog["ok.glb"]})
    assert again == {"ok.glb": "already present"}


def test_cad_catalog_is_pinned_and_https_only():
    from core.cad_models import CAD_MODELS, _fetch
    for spec in CAD_MODELS.values():
        assert spec["url"].startswith("https://raw.githubusercontent.com/KhronosGroup/")
        assert len(spec["sha256"]) == 64 and "/master/" not in spec["url"] and "/main/" not in spec["url"]
    with pytest.raises(ValueError):
        _fetch("http://example.com/x.glb")


def test_cli_download_cad_models_reports_failures(monkeypatch):
    from core import cad_models, registry_cli
    monkeypatch.setattr(cad_models, "download_cad_models", lambda: {"a.glb": "downloaded (4 bytes)"})
    assert "a.glb: downloaded" in registry_cli.run(["download-cad-models"], runtime=None)
    monkeypatch.setattr(cad_models, "download_cad_models", lambda: {"a.glb": "FAILED: boom"})
    assert registry_cli.run(["download-cad-models"], runtime=None).startswith("error:")


@needs_local_gpu_stack
def test_real_page_cad_engine_explodes_and_hover_reaches_python():
    from core.viewer3d import MODELS_DIR
    if not (MODELS_DIR / "cad" / "engine.glb").is_file():
        pytest.skip("run: python -m core.registry_cli download-cad-models")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    import ui as ui_module

    app = QApplication.instance() or QApplication(sys.argv)
    jarvis = ui_module.JarvisUI("")
    win = jarvis._win
    # a style chosen before any model is loaded is applied to the next model
    viewer_3d.viewer_3d({"mode": "set_material_style", "style": "blueprint"}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "load_model", "model": "cad/engine.glb"}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["status"] in ("ready", "error"))
    assert state["model"]["status"] == "ready", state["model"]
    assert state["model"]["style"] == "blueprint"
    assert state["model"]["parts"] >= 2
    assert state["controls"]["enabled"] is True

    # a real mouse drag on the view rotates the camera around the model
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    win.resize(900, 700)
    win.show()
    app.processEvents()
    view = win._viewer3d
    target = view.focusProxy() or view
    before = state["controls"]["azimuth"]
    start = QPoint(target.width() // 2, target.height() // 2)
    QTest.mousePress(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    for step in range(1, 21):
        QTest.mouseMove(target, start + QPoint(step * 8, 0))
        app.processEvents()
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(160, 0))
    state = _poll_state(app, win, lambda s: abs(s["controls"]["azimuth"] - before) > 0.1)
    assert abs(state["controls"]["azimuth"] - before) > 0.1, state["controls"]
    viewer_3d.viewer_3d({"mode": "set_controls", "on": False}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["controls"]["enabled"] is False)
    assert state["controls"]["enabled"] is False
    viewer_3d.viewer_3d({"mode": "set_controls", "on": True}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "spin", "spin": False}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "explode_model", "on": True}, player=jarvis)
    state = _poll_state(app, win, lambda s: s["model"]["explode"] == 1)
    assert any(d > 0.1 for d in state["model"]["moved"]), state["model"]

    scan = """
    (() => { const c = document.getElementById('c'), r = c.getBoundingClientRect();
      c.dispatchEvent(new MouseEvent('mousemove', {clientX: r.left + r.width * %d / 12, clientY: r.top + r.height * %d / 12}));
    })()
    """
    points = [(i, j) for j in range(3, 10) for i in range(3, 10)]
    deadline = time.time() + 40
    while time.time() < deadline and not jarvis.viewer3d_hover().get("name"):
        i, j = points[int((time.time() * 10) % len(points))]
        win._viewer3d.page().runJavaScript(scan % (i, j))
        end = time.time() + 0.15
        while time.time() < end:
            app.processEvents()
    hover = jarvis.viewer3d_hover()
    assert hover["name"], "no part reached Python"
    assert hover["name"] in viewer_3d.viewer_3d({"mode": "hovered_part"}, player=jarvis)
    viewer_3d.viewer_3d({"mode": "clear_model"}, player=jarvis)

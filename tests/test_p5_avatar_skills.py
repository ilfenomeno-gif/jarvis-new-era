"""Tests for P5: optional holographic avatar (behind config) and declarative
skills presence. GUI test uses offscreen Qt; no real window is shown."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QGuiApplication
    QGuiApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_hud_style_defaults_to_core(tmp_path, monkeypatch):
    from memory import config_manager as cm
    monkeypatch.setattr(cm, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "api_keys.json")
    assert cm.get_hud_style() == "core"          # opt-in: default unchanged
    cm.save_hud_style("face")
    assert cm.get_hud_style() == "face"
    cm.save_hud_style("bogus")
    assert cm.get_hud_style() == "core"


def test_avatar_off_by_default_on_by_face(qapp, tmp_path, monkeypatch):
    from memory import config_manager as cm
    monkeypatch.setattr(cm, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cm, "CONFIG_FILE", tmp_path / "api_keys.json")
    import ui as U

    cm.save_hud_style("core")
    w_core = U.HudCanvas("", "JARVIS")
    assert w_core._holo_avatar is None           # default: no avatar

    cm.save_hud_style("face")
    w_face = U.HudCanvas("", "JARVIS")
    assert w_face._holo_avatar is not None       # opt-in: avatar active


def test_declarative_skills_present():
    from core.skills import SkillRegistry
    from core.audit_log import AuditLog
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    reg = SkillRegistry(Path("skills"), tmp / "state.json", AuditLog(tmp / "a.jsonl"))
    reg.load()
    names = [s["name"] for s in reg.view()] if hasattr(reg, "view") else []
    assert "app-launcher" in names
    assert "hud-ui" in names

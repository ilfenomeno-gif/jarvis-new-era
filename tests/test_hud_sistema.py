"""Tests for the HUD SISTEMA tab and the /api/system endpoint (Jarvis VII)."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from core.hud_bridge import HudBridge


def test_hud_html_has_sistema_tab():
    html = (Path("core") / "jarvis_hud.html").read_text(encoding="utf-8")
    assert 'data-t="sistema"' in html
    assert 'id="sistema"' in html
    assert '"/api/system"' in html
    assert "sysAction" in html
    # the requested entries
    for action in ("fullscreen", "desktop_shortcut", "autostart", "remote",
                   "dictation", "customize", "audio", "memory", "plugins"):
        assert f'data-a="{action}"' in html, action
    # tab switcher includes sistema
    assert '["chat","dati","sistema"]' in html


def test_bridge_system_endpoint_fires_callback():
    hud = HudBridge(port=0)
    url = hud.start(window="none")
    time.sleep(0.5)
    received = []
    hud.on_system = lambda a: received.append(a)
    body = json.dumps({"action": "fullscreen"}).encode()
    req = urllib.request.Request(url + "/api/system", data=body,
                                 headers={"Content-Type": "application/json", "X-HUD": "1"},
                                 method="POST")
    r = urllib.request.urlopen(req, timeout=5)
    time.sleep(0.5)
    hud.stop()
    assert r.status == 204
    assert received == ["fullscreen"]


def test_bridge_system_endpoint_rejects_bad_body():
    hud = HudBridge(port=0)
    url = hud.start(window="none")
    time.sleep(0.5)
    body = json.dumps({"nope": 1}).encode()
    req = urllib.request.Request(url + "/api/system", data=body,
                                 headers={"Content-Type": "application/json", "X-HUD": "1"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    hud.stop()
    assert code == 400


def test_mainwindow_system_action_dispatch():
    """_system_action routes known actions and logs unknown ones (no Qt needed)."""
    import ui as ui_module
    calls = []
    logs = []

    class FakeWin:
        def _toggle_fullscreen(self): calls.append("fullscreen")
        def _create_desktop_shortcut(self): calls.append("desktop_shortcut")
        def _toggle_autostart(self): calls.append("autostart")
        def _open_remote(self): calls.append("remote")
        def _open_customize(self): calls.append("customize")
        def _open_audio_devices(self): calls.append("audio")
        def _open_memory_panel(self): calls.append("memory")
        def _open_plugin_manager(self): calls.append("plugins")
        def _toggle_dictation(self, enabled): calls.append(("dictation", enabled))

        class _log_sig:
            @staticmethod
            def emit(msg):
                logs.append(msg)

    win = FakeWin()
    for a in ("fullscreen", "desktop_shortcut", "autostart", "remote",
              "customize", "audio", "memory", "plugins"):
        ui_module.MainWindow._system_action(win, a)
    assert calls[:8] == ["fullscreen", "desktop_shortcut", "autostart", "remote",
                         "customize", "audio", "memory", "plugins"]
    ui_module.MainWindow._system_action(win, "dictation")
    assert ("dictation", True) in calls
    ui_module.MainWindow._system_action(win, "nope")
    assert any("unknown system action" in m for m in logs)

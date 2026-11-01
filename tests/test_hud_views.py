"""Tests for HUD top view, humanoid reveal ("Jarvis rivelati"), and layout scale."""
from __future__ import annotations

from pathlib import Path

from actions import hud_control as hc


class _Player:
    def __init__(self):
        self.commands = []

    def hud_command(self, action, **kw):
        self.commands.append((action, kw))


def test_hud_html_has_top_view_humanoid_scale():
    html = (Path("core") / "jarvis_hud.html").read_text(encoding="utf-8")
    # top view
    assert 'id="topview"' in html
    assert "setTopView" in html
    assert 'tP=1.5' in html
    # humanoid
    assert 'id="humanoidWrap"' in html
    assert "revealHumanoid" in html
    assert "mira-humanoid" in html
    assert 'allow="autoplay"' in html
    assert 'allow="camera; microphone;' not in html
    # layout scale
    assert 'id="scale"' in html
    assert 'type="range"' in html
    # command handlers
    assert 'case"top_view":setTopView' in html
    assert 'case"reveal":revealHumanoid' in html


def test_hud_control_top_view_and_reveal():
    p = _Player()
    assert hc.hud_control({"action": "top_view"}, player=p).startswith("status=done")
    assert p.commands[-1] == ("top_view", {})
    p2 = _Player()
    assert hc.hud_control({"action": "top_view", "on": True}, player=p2).startswith("status=done")
    assert p2.commands[-1] == ("top_view", {"on": True})
    p3 = _Player()
    assert hc.hud_control({"action": "reveal", "on": True}, player=p3).startswith("status=done")
    assert p3.commands[-1] == ("reveal", {"on": True})


def test_hud_control_new_actions_in_contract():
    assert "top_view" in hc.TOOL["parameters"]["properties"]["action"]["description"] or \
           "top_view" in hc.TOOL["description"]
    assert "reveal" in hc.TOOL["description"]


def test_rivelati_phrase_routes_to_reveal():
    """'Jarvis rivelati' triggers the reveal command on the HUD."""
    import main as main_module
    import inspect
    text_src = inspect.getsource(main_module.JarvisLive._on_text_command)
    voice_src = inspect.getsource(main_module.JarvisLive._route_voice_transcript)
    assert "_hud_visibility_request" in text_src
    assert "_hud_visibility_request" in voice_src
    assert "_set_hud_humanoid_visible" in text_src
    assert "_set_hud_humanoid_visible" in voice_src


def test_hud_visibility_phrase_requires_exact_jarvis_command():
    from main import JarvisLive

    assert JarvisLive._hud_visibility_request("Jarvis rivelati!") is True
    assert JarvisLive._hud_visibility_request("  JARVIS   RIVELATI  ") is True
    assert JarvisLive._hud_visibility_request("Jarvis nasconditi.") is False
    assert JarvisLive._hud_visibility_request("rivelati nella scena") is None
    assert JarvisLive._hud_visibility_request("Puoi rivelarti?") is None

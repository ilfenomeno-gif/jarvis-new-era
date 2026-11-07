"""Tests for the original map HUD, Iris reveal phrase, top view, and layout scale."""
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
    assert "<title>JARVIS Mark-LIV · Mappa 3D</title>" in html
    assert "<body>" in html
    assert "chat-only" not in html
    assert 'id="humanoidWrap" hidden' in html
    assert '#humanoidWrap{position:fixed;inset:0;width:100vw;height:100vh' in html
    assert 'body.iris-mode .hud>*:not(#info){display:none!important}' in html
    assert 'body.iris-mode #tabs,body.iris-mode #tr{display:none!important}' in html
    assert 'body.iris-mode #chat{display:flex!important}' in html
    assert 'document.body.classList.toggle("iris-mode",on)' in html
    assert 'function activateChat()' in html
    assert 'cancelAnimationFrame(renderFrame)' in html
    assert 'setPixelRatio(Math.min(devicePixelRatio||1,1.5))' in html
    assert 'now-lastRender<1000/30' in html
    assert 'src="about:blank"' in html
    assert 'let visualMode="map"' in html
    assert 'setVisualMode("mira")' not in html
    assert 'id="humanoidFrame"' in html
    assert 'const HUMANOID_URL="https://mira-humanoid.vercel.app/"' in html
    assert 'if(!humanoidLoaded){$("humanoidFrame").src=HUMANOID_URL;humanoidLoaded=true}' in html
    assert 'id="mapview"' in html
    assert 'id="hudHide"' in html
    assert 'id="hudRestore"' in html
    assert 'window.jarvisHudMessage=' in html
    assert 'body.hud-hidden .hud{display:none}' in html
    assert 'body.hud-hidden #hudRestore{display:block}' in html
    assert 'function setVisualMode(mode)' in html
    assert 'case"map_view":setVisualMode' in html
    assert 'function pick(id,open=true){if(open)setVisualMode("map")' in html
    assert 'function openSystem(id,tr){if(!tr&&touring)' in html and \
           'setVisualMode("map");if((id||"main")===view)' in html
    assert 'Iris rivelata a schermo intero.' in html
    assert 'premi ENTER per avviare' in html
    # top view
    assert 'id="topview"' in html
    assert "setTopView" in html
    assert 'tP=1.5' in html
    # humanoid
    assert 'id="humanoidWrap"' in html
    assert "revealHumanoid" in html
    assert 'allow="autoplay; microphone; camera"' in html
    # layout scale
    assert 'id="scale"' in html
    assert 'type="range"' in html
    # command handlers
    assert 'case"top_view":setTopView' in html
    assert 'case"reveal":revealHumanoid' in html


def test_initialization_splash_uses_live_runtime_and_bounded_wait():
    html = (Path("core") / "jarvis_hud.html").read_text(encoding="utf-8")
    assert 'id="bootScreen"' in html
    assert 'id="bootCanvas"' in html
    assert 'bootNodes=[],bootTotal=705,bootRows=13' in html
    assert "const exact=weights.map(w=>bootTotal*w/sum)" in html
    assert '["listening","muted","speaking"].includes(bootState)' in html
    assert 'finishBootScreen(false,"CORE CONNECTION DELAYED","CHECK STATUS")' in html
    assert 'handleBootState(assistantState)' in html
    assert 'case"state":assistantState=m.state||"unknown";showBridgeState();handleBootState(assistantState)' in html


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
    p4 = _Player()
    assert hc.hud_control({"action": "map_view"}, player=p4).startswith("status=done")
    assert p4.commands[-1] == ("map_view", {})


def test_hud_control_new_actions_in_contract():
    assert "top_view" in hc.TOOL["parameters"]["properties"]["action"]["description"] or \
           "top_view" in hc.TOOL["description"]
    assert "reveal" in hc.TOOL["description"]
    assert "map_view" in hc.TOOL["description"]


def test_rivelati_phrase_routes_to_reveal():
    """The spoken phrase "Iris rivelati" triggers the reveal command."""
    import main as main_module
    import inspect
    text_src = inspect.getsource(main_module.JarvisLive._on_text_command)
    voice_src = inspect.getsource(main_module.JarvisLive._route_voice_transcript)
    assert "_hud_visibility_request" in text_src
    assert "_hud_visibility_request" in voice_src
    assert "_set_hud_humanoid_visible" in text_src
    assert "_set_hud_humanoid_visible" in voice_src


def test_hud_visibility_phrase_requires_exact_iris_command():
    from main import JarvisLive

    assert JarvisLive._hud_visibility_request("Iris rivelati!") is True
    assert JarvisLive._hud_visibility_request("  IRIS   RIVELATI  ") is True
    assert JarvisLive._hud_visibility_request("Iris nasconditi.") is False
    assert JarvisLive._hud_visibility_request("Mira rivelati") is None
    assert JarvisLive._hud_visibility_request("rivelati nella scena") is None
    assert JarvisLive._hud_visibility_request("Puoi rivelarti?") is None

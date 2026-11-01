"""Tests for hud_control (Jarvis drives the HUD 3D map) and the HudBridge
command channel. No real HUD/browser needed."""
from __future__ import annotations

import json

from actions import hud_control as hc
from core.hud_bridge import HudBridge


class _Player:
    def __init__(self):
        self.commands = []

    def hud_command(self, action, **kw):
        self.commands.append((action, kw))


def test_unknown_action_fails():
    line = hc.hud_control({"action": "nope"}, player=_Player())
    assert line.startswith("status=failed")


def test_no_player_fails():
    line = hc.hud_control({"action": "tour"}, player=None)
    assert "not available" in line


def test_open_system_validates_and_sends():
    p = _Player()
    line = hc.hud_control({"action": "open_system", "system": "gev"}, player=p)
    assert line.startswith("status=done")
    assert p.commands == [("open_system", {"id": "gev"})]
    # unknown system
    line = hc.hud_control({"action": "open_system", "system": "nope"}, player=_Player())
    assert line.startswith("status=failed")


def test_tour_and_run():
    p = _Player()
    assert hc.hud_control({"action": "tour"}, player=p).startswith("status=done")
    assert p.commands[-1] == ("tour", {})
    p2 = _Player()
    line = hc.hud_control({"action": "run", "scenario": "Apri Netflix"}, player=p2)
    assert line.startswith("status=done")
    assert p2.commands[-1] == ("run", {"scenario": "Apri Netflix"})
    # unknown scenario
    assert hc.hud_control({"action": "run", "scenario": "x"}, player=_Player()).startswith("status=failed")


def test_say_and_set_task():
    p = _Player()
    assert hc.hud_control({"action": "say", "text": "ciao"}, player=p).startswith("status=done")
    assert p.commands[-1] == ("say", {"text": "ciao"})
    assert hc.hud_control({"action": "say", "text": "  "}, player=_Player()).startswith("status=failed")
    p2 = _Player()
    assert hc.hud_control({"action": "set_task", "progress": 50, "status": "running"}, player=p2).startswith("status=done")
    assert p2.commands[-1] == ("set_task", {"progress": 50, "status": "running"})


def test_tool_contract():
    assert hc.TOOL["risk_class"] == "read"
    assert hc.TOOL["name"] == "hud_control"
    assert "action" in hc.TOOL["parameters"]["properties"]


# ── HudBridge.command channel ────────────────────────────────────────────────
def test_bridge_command_broadcasts():
    hud = HudBridge()
    received = []
    import queue as _q
    q = _q.Queue()
    with hud._lock:
        hud._clients.add(q)
    hud.command("open_system", id="gev")
    msg = json.loads(q.get(timeout=2))
    assert msg["type"] == "command"
    assert msg["action"] == "open_system"
    assert msg["id"] == "gev"


def test_hud_html_handles_command():
    from pathlib import Path
    html = (Path("core") / "jarvis_hud.html").read_text(encoding="utf-8")
    assert 'case"command":handleCommand(m)' in html
    assert "function handleCommand" in html
    assert 'openSystem(m.id)' in html
    assert "run(m.scenario)" in html

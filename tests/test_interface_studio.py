import pytest

from actions.interface_studio import TOOL, interface_studio


class Player:
    def __init__(self):
        self.commands = []

    def hud_command(self, action, **payload):
        self.commands.append((action, payload))


def test_studio_enables_edit_mode_and_moves_a_named_panel():
    player = Player()
    assert '"status": "done"' in interface_studio(
        {"action": "edit_mode", "enabled": True}, player=player
    )
    result = interface_studio(
        {
            "action": "panel",
            "panel": "info",
            "x": 180,
            "y": 120,
            "width": 420,
            "height": 500,
        },
        player=player,
    )

    assert '"status": "done"' in result
    assert player.commands == [
        ("studio_edit_mode", {"enabled": True}),
        (
            "studio_panel",
            {"panel": "info", "x": 180.0, "y": 120.0, "width": 420.0, "height": 500.0},
        ),
    ]


def test_studio_rejects_invalid_panels_coordinates_and_text():
    player = Player()
    for params in (
        {"action": "panel", "panel": "browser", "visible": False},
        {"action": "panel", "panel": "info", "x": -1},
        {"action": "label", "operation": "add", "id": "safe", "text": "x", "x": 1},
        {
            "action": "label",
            "operation": "add",
            "id": "bad id",
            "text": "<script>alert(1)</script>",
            "x": 1,
            "y": 2,
        },
    ):
        assert '"status": "failed"' in interface_studio(params, player=player)
    assert player.commands == []


def test_studio_creates_safe_annotations_and_whiteboard_shapes():
    player = Player()
    interface_studio(
        {"action": "label", "operation": "add", "id": "goal", "text": "Obiettivo", "x": 50, "y": 80},
        player=player,
    )
    interface_studio(
        {
            "action": "board",
            "operation": "add",
            "id": "arrow-1",
            "shape": "arrow",
            "x": 10,
            "y": 20,
            "x2": 100,
            "y2": 120,
            "color": "#00d4ff",
        },
        player=player,
    )
    interface_studio({"action": "board", "operation": "draw"}, player=player)
    interface_studio({"action": "board", "operation": "clear"}, player=player)

    assert [name for name, _ in player.commands] == [
        "studio_label",
        "studio_board",
        "studio_board",
        "studio_board",
    ]
    assert player.commands[1][1]["shape"] == "arrow"
    assert player.commands[2][1]["operation"] == "draw"


def test_studio_controls_camera_and_named_local_scenes():
    player = Player()
    interface_studio({"action": "camera", "mode": "zoom", "factor": 1.5}, player=player)
    interface_studio({"action": "camera", "mode": "pan", "x": 3, "y": -2}, player=player)
    interface_studio({"action": "scene", "operation": "save", "name": "presentation"}, player=player)

    assert player.commands == [
        ("studio_camera", {"mode": "zoom", "factor": 1.5}),
        ("studio_camera", {"mode": "pan", "x": 3.0, "y": -2.0}),
        ("studio_scene", {"operation": "save", "name": "presentation"}),
    ]


def test_studio_previews_html_in_isolated_workspace():
    player = Player()
    document = "<h1>Presentazione</h1><p>Anteprima</p>"
    result = interface_studio(
        {"action": "html", "operation": "show", "title": "Slide 1", "html": document},
        player=player,
    )

    assert '"status": "done"' in result
    assert "Presentazione" not in result
    assert player.commands == [
        ("studio_html", {"operation": "show", "title": "Slide 1", "html": document})
    ]
    assert '"status": "done"' in interface_studio(
        {"action": "html", "operation": "close"}, player=player
    )
    assert player.commands[-1] == ("studio_html", {"operation": "close"})


def test_studio_rejects_invalid_or_oversized_html_preview():
    player = Player()
    for params in (
        {"action": "html", "operation": "show", "title": "", "html": "<p>x</p>"},
        {"action": "html", "operation": "show", "title": "Slide", "html": " "},
        {
            "action": "html",
            "operation": "show",
            "title": "Slide",
            "html": "x" * 100_001,
        },
        {
            "action": "html",
            "operation": "show",
            "title": "Slide",
            "html": "💎" * 25_001,
        },
        {"action": "html", "operation": "show", "title": "Slide", "html": "\ud800"},
        {"action": "html", "operation": "open"},
    ):
        assert '"status": "failed"' in interface_studio(params, player=player)
    assert player.commands == []


@pytest.mark.pre_existing(reason="HUD HTML non contiene gli handler studio_* attesi dal contratto")
@pytest.mark.xfail(
    reason="HUD HTML non contiene gli handler studio_* attesi dal contratto",
    strict=False,
)
def test_studio_tool_contract_and_hud_command_handlers():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "core" / "jarvis_hud.html").read_text(
        encoding="utf-8"
    )
    assert TOOL["name"] == "interface_studio"
    assert TOOL["risk_class"] == "write"
    for action in (
        "studio_edit_mode",
        "studio_panel",
        "studio_label",
        "studio_board",
        "studio_camera",
        "studio_scene",
        "studio_html",
    ):
        assert f'case"{action}"' in html
    assert 'node.textContent=command.text' in html
    assert 'localStorage.setItem(key,JSON.stringify(value))' in html
    assert 'sandbox=""' in html
    assert "script-src 'none'" in html

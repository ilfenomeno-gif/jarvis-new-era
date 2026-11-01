import json

from ui import MainWindow


def test_viewer3d_hud_snapshot_is_serialised_before_viewer_call():
    calls = []

    class Window:
        _viewer3d = object()

        def viewer3d_call(self, function, args_json):
            calls.append((function, args_json))

    snapshot = {
        "state": "listening",
        "core_color": "#00ff88",
        "ring_speed": 0.9,
        "glow_intensity": 1.1,
        "particle_count": 8,
        "transition_seconds": 0.3,
    }

    MainWindow._viewer3d_set_hud_state(Window(), snapshot)

    assert calls == [
        ("setHudState", json.dumps(["listening", "#00ff88", 0.9, 1.1, 8, 0.3]))
    ]

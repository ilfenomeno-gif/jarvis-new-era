import json
from pathlib import Path

import pytest

from core.hud_animator import HudAnimator, STATE_NAMES, load_configuration


CONFIG_SOURCE = Path(__file__).resolve().parents[1] / "config"


def _copy_configuration(destination: Path) -> Path:
    destination.mkdir()
    for name in ("hud_states.json", "hud_transitions.json"):
        (destination / name).write_text(
            (CONFIG_SOURCE / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return destination


def test_default_configuration_defines_all_states_and_valid_transitions():
    states, transitions = load_configuration(CONFIG_SOURCE)

    assert set(states) == STATE_NAMES
    assert states["listening"]["core_color"] == "#00ff88"
    assert states["thinking"]["core_color"] == "#ff8a00"
    assert states["speaking"]["core_color"] == "#ff00d4"
    assert states["generating_3d"]["particle_count"] > states["idle"]["particle_count"]
    assert transitions["transitions"]["listening->thinking"] == 0.3


def test_state_changes_interpolate_all_animated_properties():
    clock = [1.0]
    animator = HudAnimator(CONFIG_SOURCE, clock=lambda: clock[0])
    animator.set_state("listening")

    middle = animator.update(now=1.15, _allow_reload=False)
    assert middle["state"] == "listening"
    assert middle["core_color"] not in ("#00d4ff", "#00ff88")
    assert 0.55 < middle["ring_speed"] < 0.9
    assert 3 < middle["particle_count"] < 8

    animator.set_state("thinking", now=1.15)
    assert animator.target_snapshot()["transition_seconds"] == 0.3
    assert animator.update(now=2.0, _allow_reload=False)["core_color"] == "#ff8a00"


def test_cli_reload_notifies_and_updates_an_active_animator(tmp_path, monkeypatch):
    from core import registry_cli

    config_dir = _copy_configuration(tmp_path / "config")
    animator = HudAnimator(config_dir, clock=lambda: 5.0)
    states_path = config_dir / "hud_states.json"
    data = json.loads(states_path.read_text(encoding="utf-8"))
    data["states"]["idle"]["core_color"] = "#123456"
    states_path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(registry_cli, "BASE_DIR", tmp_path)

    result = registry_cli.run(["reload_hud_states"], runtime=None)

    assert "reload requested" in result
    assert animator.poll_reload(now=5.0)
    assert animator.update(now=6.0, _allow_reload=False)["core_color"] == "#123456"
    assert not animator.poll_reload(now=6.0)


def test_invalid_reload_keeps_the_active_configuration(tmp_path):
    config_dir = _copy_configuration(tmp_path / "config")
    animator = HudAnimator(config_dir)
    (config_dir / "hud_states.json").write_text('{"states": {}}', encoding="utf-8")

    with pytest.raises(ValueError, match="exactly the six"):
        animator.reload()

    assert animator.states["idle"]["core_color"] == "#00d4ff"

from pathlib import Path

import pytest

from core.subway_surfer import (
    DOM_SNAPSHOT_SCRIPT,
    FRAME_DOM_PROBE_SCRIPT,
    build_game_snapshot_script,
    build_read_game_snapshot_script,
    decode_game_plan,
    key_for_action,
    play_subway_surfer,
    resolve_max_actions,
    select_game_frame,
    validate_action_safety,
)
from core.game_agent_memory import GameAgentMemory


def make_plan(action="wait", *, lane="center", obstacles=None, confidence=0.9):
    return {
        "analysis": {
            "player_lane": lane,
            "confidence": confidence,
            "obstacles": obstacles or [],
        },
        "action": action,
        "reason": "Obstacle analysis complete",
        "verification": {
            "status": "not_applicable",
            "evidence": "",
        },
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 20), (1, 1), (60, 60)],
)
def test_max_actions_are_bounded(value, expected):
    assert resolve_max_actions(value) == expected


@pytest.mark.parametrize("value", [True, 0, 61, "20"])
def test_invalid_action_limits_are_rejected(value):
    with pytest.raises(ValueError):
        resolve_max_actions(value)


def test_game_plan_requires_explicit_obstacle_analysis():
    plan = make_plan("jump", obstacles=[{
        "lane": "center",
        "type": "barrier",
        "distance": "near",
    }])
    assert decode_game_plan(plan) == {
        "action": "jump",
        "reason": "Obstacle analysis complete",
        "verification": {
            "status": "not_applicable",
            "evidence": "",
        },
        "analysis": {
            "player_lane": "center",
            "confidence": 0.9,
            "obstacles": [{
                "lane": "center",
                "type": "barrier",
                "distance": "near",
            }],
        },
    }
    with pytest.raises(ValueError, match="unsupported game action"):
        decode_game_plan({**make_plan(), "action": "open_url"})
    with pytest.raises(ValueError, match="reason must be text"):
        decode_game_plan({**make_plan(), "reason": []})
    with pytest.raises(ValueError, match="analyze"):
        decode_game_plan({"action": "jump", "reason": "Obstacle ahead"})
    with pytest.raises(ValueError, match="verification status"):
        decode_game_plan({**make_plan(), "verification": {"status": "maybe"}})


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("left", "ArrowLeft"),
        ("right", "ArrowRight"),
        ("jump", "ArrowUp"),
        ("slide", "ArrowDown"),
        ("start", "Enter"),
        ("wait", None),
        ("done", None),
    ],
)
def test_game_actions_map_to_fixed_browser_keys(action, expected):
    assert key_for_action(action) == expected


@pytest.mark.parametrize(
    ("action", "expected"),
    [("left", "a"), ("right", "d"), ("jump", "w"), ("slide", "s")],
)
def test_game_actions_support_wasd(action, expected):
    assert key_for_action(action, "wasd") == expected


def test_dom_snapshot_is_fixed_and_reads_visible_game_state():
    assert "document.body.innerText" in DOM_SNAPSHOT_SCRIPT
    assert "querySelectorAll" in DOM_SNAPSHOT_SCRIPT
    assert ".slice(0, 4000)" in DOM_SNAPSHOT_SCRIPT
    assert "eval(" not in DOM_SNAPSHOT_SCRIPT


def test_game_snapshot_requests_sanitized_dom_from_cross_origin_frames():
    script = build_game_snapshot_script("request123")

    assert script.startswith("(() =>")
    assert "JARVIS_SUBWAY_DOM_REQUEST" in script
    assert "JARVIS_SUBWAY_DOM_RESPONSE" in script
    assert "snapshots.find" in script
    assert "return true; })()" in script
    assert "document.body.innerText" in FRAME_DOM_PROBE_SCRIPT
    read_script = build_read_game_snapshot_script("request123")
    assert "delete snapshots" in read_script
    assert "return result" in read_script
    with pytest.raises(ValueError, match="request_id"):
        build_game_snapshot_script("bad-id;alert(1)")
    with pytest.raises(ValueError, match="request_id"):
        build_read_game_snapshot_script("bad-id;alert(1)")


def test_game_frame_is_selected_from_poki_iframe_metadata():
    frame = {
        "title": "Game",
        "src": "https://games.poki.com/game",
        "rect": {"x": 20, "y": 30, "width": 800, "height": 450},
        "dom": None,
    }
    assert select_game_frame({
        "title": "Subway Surfers - Play Online",
        "url": "https://poki.com/en/g/subway-surfers",
        "text": "Subway Surfers",
        "frames": [frame],
    }) == frame
    with pytest.raises(RuntimeError, match="Subway Surfers"):
        select_game_frame({"title": "Other game", "url": "https://example.com"})


@pytest.mark.parametrize(
    ("lane", "obstacles", "action", "expected"),
    [
        ("center", [{"lane": "center", "type": "train", "distance": "near"}], "wait", "left"),
        ("left", [{"lane": "left", "type": "barrier", "distance": "near"}], "jump", "jump"),
        ("center", [{"lane": "left", "type": "train", "distance": "near"}], "left", "right"),
        ("right", [{"lane": "right", "type": "overhead", "distance": "near"}], "wait", "left"),
    ],
)
def test_nearby_hazard_safety_changes_unsafe_or_boundary_moves(
    lane, obstacles, action, expected
):
    plan = decode_game_plan(
        make_plan(action, lane=lane, obstacles=obstacles)
    )
    assert validate_action_safety(plan) == expected


def test_obstacle_in_next_lane_is_treated_as_unsafe_even_at_mid_distance():
    plan = decode_game_plan(make_plan(
        "right",
        obstacles=[{
            "lane": "right",
            "type": "train",
            "distance": "mid",
        }],
    ))

    assert validate_action_safety(plan) == "left"


def test_nearby_unavoidable_hazards_fail_closed():
    plan = decode_game_plan(make_plan(
        "wait",
        obstacles=[
            {"lane": "center", "type": "train", "distance": "near"},
            {"lane": "left", "type": "train", "distance": "near"},
            {"lane": "right", "type": "train", "distance": "near"},
        ],
    ))
    with pytest.raises(RuntimeError, match="nessun tasto inviato"):
        validate_action_safety(plan)


def test_game_loop_uses_vision_plan_and_only_game_keys():
    class Player:
        def __init__(self):
            self.keys = []
            self.captures = 0

        def capture_subway_surfer_state(self):
            self.captures += 1
            return {"dom": {"text": "Subway Surfers"}, "image_png": b"png"}

        def press_key_in_subway_surfer(self, key, *, action):
            self.keys.append(key)

    player = Player()
    plans = iter(
        [
            make_plan("jump", obstacles=[{
                "lane": "center", "type": "barrier", "distance": "near",
            }]),
            make_plan("left"),
            make_plan("done"),
        ]
    )
    armed = []
    pauses = []

    result = play_subway_surfer(
        player,
        10,
        planner=lambda _state, _history, _step, _limit: next(plans),
        arm_stop=lambda: armed.append(True),
        stop_requested=lambda: False,
        pause=pauses.append,
    )

    assert result == {
        "result": "success",
        "actions": 2,
        "reason": "Obstacle analysis complete",
        "analysis": {
            "player_lane": "center",
            "confidence": 0.9,
            "obstacles": [],
        },
    }
    assert player.keys == ["ArrowUp", "ArrowLeft"]
    assert player.captures == 3
    assert armed == [True]
    assert pauses == [0.2, 0.2]


def test_game_loop_stops_before_key_if_emergency_stop_is_triggered():
    class Player:
        def capture_subway_surfer_state(self):
            return {"dom": {}, "image_png": b"png"}

        def press_key_in_subway_surfer(self, _key):
            pytest.fail("No game key should be sent after the emergency stop.")

    checks = iter([False, True])
    result = play_subway_surfer(
        Player(),
        1,
        planner=lambda *_args: make_plan("jump", obstacles=[{
            "lane": "center", "type": "barrier", "distance": "near",
        }]),
        arm_stop=lambda: None,
        stop_requested=lambda: next(checks),
    )

    assert result == {"result": "killed", "actions": 0}


def test_game_loop_stops_without_input_when_visual_confidence_is_low():
    class Player:
        def capture_subway_surfer_state(self):
            return {"dom": {}, "image_png": b"png"}

        def press_key_in_subway_surfer(self, *_args, **_kwargs):
            pytest.fail("An uncertain visual decision must not send input.")

    result = play_subway_surfer(
        Player(),
        1,
        planner=lambda *_args: make_plan("jump", confidence=0.2),
        arm_stop=lambda: None,
        stop_requested=lambda: False,
    )

    assert result["result"] == "uncertain"
    assert "nessun tasto inviato" in result["reason"]


def test_game_loop_discards_stale_visual_decision(monkeypatch):
    class Player:
        def capture_subway_surfer_state(self):
            return {"dom": {}, "image_png": b"png"}

        def press_key_in_subway_surfer(self, *_args, **_kwargs):
            pytest.fail("A stale vision decision must never send a key.")

    times = iter([1.0, 4.1])
    monkeypatch.setattr("core.subway_surfer.time.monotonic", lambda: next(times))
    result = play_subway_surfer(
        Player(),
        1,
        planner=lambda *_args: make_plan("left"),
        arm_stop=lambda: None,
        stop_requested=lambda: False,
    )

    assert result["result"] == "stale"
    assert "nessun tasto inviato" in result["reason"]


def test_game_agent_memory_triggers_events_and_learns_from_verification():
    memory = GameAgentMemory()
    initial_context = memory.prompt_context(1)
    assert initial_context["controller"] == "strategic"
    assert "episode_start" in initial_context["events"]

    start = decode_game_plan(make_plan())
    assert memory.observe(start["analysis"], start["verification"], 1) == ([], None)
    memory.record_action(start["analysis"], "left", 1)

    moved = decode_game_plan(make_plan(lane="left", obstacles=[{
        "lane": "left", "type": "train", "distance": "mid",
    }]))
    events, target_lane = memory.observe(moved["analysis"], {
        "status": "uncertain",
        "evidence": "",
    }, 2)

    assert "lane_change_observed" in events
    assert "current_lane_threatened" in events
    assert "action_verified" in events
    assert target_lane in {"center", "right"}
    assert memory.knowledge_graph == {}


def test_game_agent_memory_builds_hazard_action_knowledge_graph():
    memory = GameAgentMemory()
    before = decode_game_plan(make_plan(
        lane="center",
        obstacles=[{"lane": "center", "type": "train", "distance": "mid"}],
    ))
    memory.observe(before["analysis"], before["verification"], 1)
    memory.record_action(before["analysis"], "left", 1)

    after = decode_game_plan(make_plan(lane="left"))
    memory.observe(after["analysis"], {"status": "uncertain", "evidence": ""}, 2)

    assert memory.knowledge_graph["train"]["left"] == {
        "attempted": 1,
        "verified": 1,
        "failed": 0,
        "uncertain": 0,
    }


def test_game_loop_reacquires_low_confidence_scene_before_stopping():
    class Player:
        def __init__(self):
            self.captures = 0
            self.keys = []

        def capture_subway_surfer_state(self):
            self.captures += 1
            return {"dom": {}, "image_png": b"png"}

        def press_key_in_subway_surfer(self, key, *, action):
            self.keys.append(key)

    player = Player()
    plans = iter([make_plan("left", confidence=0.2), make_plan("left", confidence=0.2)])
    result = play_subway_surfer(
        player,
        1,
        planner=lambda *_args: next(plans),
        arm_stop=lambda: None,
        stop_requested=lambda: False,
        pause=lambda _delay: None,
    )

    assert result["result"] == "uncertain"
    assert player.captures == 2
    assert player.keys == []


def test_game_loop_passes_hierarchical_memory_to_planner():
    contexts = []

    class Player:
        def capture_subway_surfer_state(self):
            return {"dom": {}, "image_png": b"png"}

    def planner(_state, history, _step, _limit):
        contexts.append(history[-1]["agent"])
        return make_plan("done")

    result = play_subway_surfer(
        Player(),
        1,
        planner=planner,
        arm_stop=lambda: None,
        stop_requested=lambda: False,
    )

    assert result["result"] == "success"
    assert contexts[0]["controller"] == "strategic"
    assert "episode_start" in contexts[0]["events"]


def test_subway_surfer_action_is_registered_and_routed():
    from core.action_loader import discover_actions
    from core.tool_router import ToolRouter

    root = Path(__file__).resolve().parents[1]
    registry = discover_actions(root / "actions", logger=lambda _message: None)
    declarations = {
        declaration["name"]: declaration
        for declaration in registry.get_tool_declarations()
    }

    assert "subway_surfer" in declarations
    assert registry.risk_class("subway_surfer") == "write"
    assert "max_actions" in declarations["subway_surfer"]["parameters"]["properties"]
    router = ToolRouter()
    for request in (
        "Gioca a Subway Surf in modo autonomo",
        "Gioca a Subway Surfers in modo autonomo",
    ):
        assert "subway_surfer" in {
            declaration["name"]
            for declaration in router.select_for_request(request, list(declarations.values()))
        }

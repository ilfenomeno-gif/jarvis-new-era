from core.game_vision import GameObstacle, GameState, GameVision, parse_game_text


def test_perceive_uses_mock_frame_and_extracts_hud_state():
    vision = GameVision(
        frame_provider=lambda: b"mock-frame",
        frame_analyzer=lambda frame: (
            "Score: 1,250\nCenter lane\nTrain in center\nGame Over"
            if frame == b"mock-frame"
            else ""
        ),
    )

    state = vision.perceive()

    assert state.score == 1250
    assert state.lane == "center"
    assert state.obstacles == (GameObstacle("center", "train"),)
    assert state.crashed is True
    assert state.active is False


def test_perceive_accepts_structured_cv_result():
    vision = GameVision(
        frame_provider=lambda: b"frame",
        frame_analyzer=lambda _: {
            "score": 42,
            "lane": "left",
            "obstacles": [{"lane": "center", "kind": "barrier", "distance": "mid"}],
        },
    )

    assert vision.perceive() == GameState(
        score=42,
        lane="left",
        obstacles=(GameObstacle("center", "barrier", "mid"),),
    )


def test_perceive_rejects_empty_frame_and_invalid_analysis():
    import pytest

    with pytest.raises(RuntimeError, match="empty or invalid frame"):
        GameVision(frame_provider=lambda: b"", frame_analyzer=lambda _: "").perceive()
    with pytest.raises(ValueError, match="invalid game state"):
        GameVision(
            frame_provider=lambda: b"frame",
            frame_analyzer=lambda _: {"score": -1},
        ).perceive()


def test_text_parser_handles_no_hud_facts_conservatively():
    state = parse_game_text("An unreadable screen")
    assert state.score is None
    assert state.lane is None
    assert state.obstacles == ()
    assert not state.crashed

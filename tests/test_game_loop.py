import sqlite3

import pytest

from agents.game_player_agent import GamePlayerAgent
from core.game_input import GameInput
from core.game_loop import GameLoop, decide_action
from core.game_vision import GameObstacle, GameState


class SequenceVision:
    def __init__(self, states):
        self.states = iter(states)
        self.calls = 0

    def perceive(self):
        self.calls += 1
        return next(self.states)


class RecordingInput:
    def __init__(self):
        self.actions = []

    def swipe_left(self):
        self.actions.append("left")

    def swipe_right(self):
        self.actions.append("right")

    def jump(self):
        self.actions.append("jump")

    def roll(self):
        self.actions.append("roll")


def _loop(tmp_path, states, **kwargs):
    return GameLoop(
        SequenceVision(states),
        RecordingInput(),
        tmp_path / "game.sqlite3",
        poll_interval=0,
        **kwargs,
    )


def test_loop_stops_on_crash_and_logs_session(tmp_path):
    loop = _loop(
        tmp_path,
        [
            GameState(score=20, lane="center"),
            GameState(score=23, crashed=True, active=False),
        ],
    )

    result = loop.run(max_duration=10)

    assert result.end_reason == "crash"
    assert result.score == 23
    assert result.steps == 0
    with sqlite3.connect(loop.database_path) as connection:
        row = connection.execute(
            "SELECT score, end_reason, steps FROM game_sessions"
        ).fetchone()
    assert row == (23, "crash", 0)


def test_loop_stops_at_target_score_after_verifying_action(tmp_path):
    loop = _loop(
        tmp_path,
        [
            GameState(
                score=90,
                lane="center",
                obstacles=(GameObstacle("center", "train", "near"),),
            ),
            GameState(score=100, lane="left"),
        ],
    )

    result = loop.run(target_score=100, max_duration=10)

    assert result.end_reason == "target_score"
    assert result.score == 100
    assert result.steps == 1


def test_loop_stops_on_timeout(tmp_path):
    times = iter((0.0, 0.0, 1.0, 1.0))
    loop = _loop(
        tmp_path,
        [GameState(score=4, lane="center")],
        clock=lambda: next(times),
        sleeper=lambda _: None,
    )

    result = loop.run(max_duration=0.5)

    assert result.end_reason == "timeout"
    assert result.steps == 0


def test_user_stop_is_a_stop_condition(tmp_path):
    loop = _loop(tmp_path, [GameState(score=1, lane="center")])

    result = loop.run(max_duration=10, stop_requested=lambda: True)

    assert result.end_reason == "user_stop"
    assert result.steps == 0


def test_decision_selects_safe_lane_then_jump_or_roll():
    assert decide_action(
        GameState(
            lane="center",
            obstacles=(
                GameObstacle("center", "train"),
                GameObstacle("left", "train"),
            ),
        )
    ) == "right"
    assert decide_action(
        GameState(
            lane="center",
            obstacles=(
                GameObstacle("center", "barrier"),
                GameObstacle("left", "train"),
                GameObstacle("right", "train"),
            ),
        )
    ) == "jump"
    assert decide_action(
        GameState(
            lane="center",
            obstacles=(
                GameObstacle("center", "overhead"),
                GameObstacle("left", "train"),
                GameObstacle("right", "train"),
            ),
        )
    ) == "roll"


def test_loop_records_errors_before_propagating(tmp_path):
    class BrokenVision:
        def perceive(self):
            raise RuntimeError("vision unavailable")

    loop = GameLoop(BrokenVision(), RecordingInput(), tmp_path / "game.sqlite3")

    with pytest.raises(RuntimeError, match="vision unavailable"):
        loop.run(max_duration=10)

    with sqlite3.connect(loop.database_path) as connection:
        row = connection.execute(
            "SELECT end_reason FROM game_sessions"
        ).fetchone()
    assert row == ("error",)


def test_game_player_agent_starts_and_stops_loop():
    class StoppableLoop:
        def run(self, **kwargs):
            event = kwargs["stop_requested"]
            assert event.wait(1)
            return "stopped"

    agent = GamePlayerAgent(loop=StoppableLoop())
    agent.start(max_duration=10)
    result = agent.stop(timeout=1)

    assert result == "stopped"
    assert not agent.running

"""Bounded perceive-decide-act-verify loop and private SQLite session log."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Literal

from core.game_input import GameInput
from core.game_vision import GameObstacle, GameState
from core.internal_workflow import default_database_path

EndReason = Literal[
    "crash",
    "target_score",
    "timeout",
    "user_stop",
    "max_steps",
    "error",
]
Action = Literal["left", "right", "jump", "roll"]

_DISTANCE_ORDER = {"near": 0, "mid": 1, "far": 2}
_LANE_ORDER = ("left", "center", "right")


@dataclass(frozen=True)
class GameSessionResult:
    session_id: str
    score: int
    duration_seconds: float
    end_reason: EndReason
    steps: int


def decide_action(state: GameState) -> Action | None:
    """Choose a simple deterministic dodge from the closest reported hazard."""
    if state.crashed or not state.active or state.lane is None:
        return None
    lane_obstacles = [
        obstacle for obstacle in state.obstacles if obstacle.lane == state.lane
    ]
    if not lane_obstacles:
        return None
    hazard = min(lane_obstacles, key=lambda item: _DISTANCE_ORDER[item.distance])
    if hazard.distance == "far":
        return None
    lane_index = _LANE_ORDER.index(state.lane)
    occupied = {
        obstacle.lane
        for obstacle in state.obstacles
        if obstacle.distance in {"near", "mid"}
    }
    for target_index in (lane_index - 1, lane_index + 1):
        if 0 <= target_index < len(_LANE_ORDER):
            target = _LANE_ORDER[target_index]
            if target not in occupied:
                return "left" if target_index < lane_index else "right"
    if hazard.kind in {"barrier", "gap"}:
        return "jump"
    if hazard.kind in {"low_barrier", "overhead"}:
        return "roll"
    return None


class GameLoop:
    def __init__(
        self,
        vision,
        game_input: GameInput,
        database_path: str | Path | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        poll_interval: float = 0.05,
        max_steps: int = 1000,
    ) -> None:
        if not 0 <= poll_interval <= 1:
            raise ValueError("poll_interval must be between 0 and 1 second.")
        if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer.")
        self.vision = vision
        self.game_input = game_input
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.clock = clock
        self.sleeper = sleeper
        self.poll_interval = poll_interval
        self.max_steps = max_steps
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS game_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    end_reason TEXT NOT NULL,
                    steps INTEGER NOT NULL,
                    final_state_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _stopped(stop_requested: Callable[[], bool] | threading.Event | None) -> bool:
        if stop_requested is None:
            return False
        if isinstance(stop_requested, threading.Event):
            return stop_requested.is_set()
        return bool(stop_requested())

    def run(
        self,
        *,
        target_score: int | None = None,
        max_duration: float = 300,
        stop_requested: Callable[[], bool] | threading.Event | None = None,
    ) -> GameSessionResult:
        if target_score is not None and (
            isinstance(target_score, bool)
            or not isinstance(target_score, int)
            or target_score < 0
        ):
            raise ValueError("target_score must be a non-negative integer or None.")
        if (
            isinstance(max_duration, bool)
            or not isinstance(max_duration, (int, float))
            or not 0 < max_duration <= 3600
        ):
            raise ValueError("max_duration must be greater than 0 and at most 3600 seconds.")

        session_id = str(uuid.uuid4())
        started = self.clock()
        started_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        steps = 0
        state = GameState()
        end_reason: EndReason = "max_steps"
        try:
            while True:
                elapsed = max(0.0, self.clock() - started)
                if self._stopped(stop_requested):
                    end_reason = "user_stop"
                    break
                if elapsed >= max_duration:
                    end_reason = "timeout"
                    break
                if steps >= self.max_steps:
                    end_reason = "max_steps"
                    break

                state = self.vision.perceive()
                if state.crashed or not state.active:
                    end_reason = "crash"
                    break
                if target_score is not None and (state.score or 0) >= target_score:
                    end_reason = "target_score"
                    break

                action = decide_action(state)
                if action is None:
                    self.sleeper(self.poll_interval)
                    continue
                if self._stopped(stop_requested):
                    end_reason = "user_stop"
                    break
                if self.clock() - started >= max_duration:
                    end_reason = "timeout"
                    break

                getattr(self.game_input, {
                    "left": "swipe_left",
                    "right": "swipe_right",
                    "jump": "jump",
                    "roll": "roll",
                }[action])()
                steps += 1

                # Verification is a fresh observation, not an assumption that input worked.
                state = self.vision.perceive()
                if state.crashed or not state.active:
                    end_reason = "crash"
                    break
                if target_score is not None and (state.score or 0) >= target_score:
                    end_reason = "target_score"
                    break
                if self._stopped(stop_requested):
                    end_reason = "user_stop"
                    break
                if self.clock() - started >= max_duration:
                    end_reason = "timeout"
                    break
        except Exception:
            end_reason = "error"
            self._save(
                session_id,
                started_at,
                self._score(state),
                max(0.0, self.clock() - started),
                end_reason,
                steps,
                state,
            )
            raise

        duration = max(0.0, self.clock() - started)
        result = GameSessionResult(
            session_id=session_id,
            score=self._score(state),
            duration_seconds=round(duration, 3),
            end_reason=end_reason,
            steps=steps,
        )
        self._save(
            session_id,
            started_at,
            result.score,
            result.duration_seconds,
            end_reason,
            steps,
            state,
        )
        return result

    @staticmethod
    def _score(state: GameState) -> int:
        return state.score if state.score is not None else 0

    def _save(
        self,
        session_id: str,
        started_at: str,
        score: int,
        duration: float,
        end_reason: EndReason,
        steps: int,
        state: GameState,
    ) -> None:
        payload = json.dumps(
            {
                "score": state.score,
                "lane": state.lane,
                "obstacles": [
                    {"lane": item.lane, "kind": item.kind, "distance": item.distance}
                    for item in state.obstacles
                ],
                "crashed": state.crashed,
                "active": state.active,
            },
            sort_keys=True,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO game_sessions (
                    session_id, started_at, finished_at, score, duration_seconds,
                    end_reason, steps, final_state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    started_at,
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    score,
                    duration,
                    end_reason,
                    steps,
                    payload,
                ),
            )

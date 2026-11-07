"""Bounded hierarchical memory and event triggers for game-control episodes."""
from __future__ import annotations

import json
from typing import Any


_DISTANCE_RANK = {"far": 0, "mid": 1, "near": 2}
_LANES = ("left", "center", "right")


def _state_key(analysis: dict[str, Any]) -> str:
    hazards = sorted(
        (
            obstacle["lane"],
            obstacle["type"],
            obstacle["distance"],
        )
        for obstacle in analysis["obstacles"]
    )
    return json.dumps(
        [analysis["player_lane"], hazards],
        separators=(",", ":"),
        ensure_ascii=True,
    )


class GameAgentMemory:
    """Keep working, state-action, and hazard/action memories for one run."""

    def __init__(self) -> None:
        self.working_memory: list[dict[str, Any]] = []
        self.state_action_bank: dict[str, dict[str, dict[str, int]]] = {}
        self.knowledge_graph: dict[str, dict[str, dict[str, int]]] = {}
        self.pending_action: dict[str, Any] | None = None
        self.previous_analysis: dict[str, Any] | None = None
        self.last_verification = "not_applicable"
        self.last_events: list[str] = []

    def prompt_context(self, step: int) -> dict[str, Any]:
        events = list(self.last_events)
        if step == 1:
            events.append("episode_start")
        if self.pending_action is not None:
            events.append("verify_previous_action")
        if step > 1 and step % 5 == 0:
            events.append("periodic_strategy_review")
        strategic_triggers = {
            "episode_start",
            "periodic_strategy_review",
            "new_hazard",
            "hazard_closing",
            "lane_change_observed",
            "confidence_drop",
            "active_reperception",
            "current_lane_threatened",
            "action_failed",
            "action_uncertain",
        }
        return {
            "controller": (
                "strategic"
                if strategic_triggers.intersection(events)
                else "reactive"
            ),
            "events": list(dict.fromkeys(events)),
            "goal": "sopravvivere mantenendo un percorso sicuro",
            "working_memory": self.working_memory[-5:],
            "knowledge_graph": self._compact_graph(),
        }

    def observe(
        self,
        analysis: dict[str, Any],
        verification: dict[str, str],
        step: int,
    ) -> tuple[list[str], str | None]:
        events = []
        previous = self.previous_analysis
        if previous is not None:
            if previous["player_lane"] != analysis["player_lane"]:
                events.append("lane_change_observed")
            old_hazards = {
                (item["lane"], item["type"]): _DISTANCE_RANK[item["distance"]]
                for item in previous["obstacles"]
            }
            for item in analysis["obstacles"]:
                key = (item["lane"], item["type"])
                rank = _DISTANCE_RANK[item["distance"]]
                if key not in old_hazards and rank > 0:
                    events.append("new_hazard")
                elif rank > old_hazards.get(key, rank):
                    events.append("hazard_closing")
            if analysis["confidence"] < previous["confidence"]:
                events.append("confidence_drop")
        if analysis["confidence"] < 0.75:
            events.append("active_reperception")
        if self.pending_action is not None:
            result = self._verify_pending(analysis, verification)
            self.last_verification = result
            events.append(f"action_{result}")
        if step % 5 == 0:
            events.append("strategic_review")

        current_lane = analysis["player_lane"]
        target_lane = None
        if current_lane in {
            item["lane"]
            for item in analysis["obstacles"]
            if item["distance"] in {"mid", "near"}
        }:
            target_lane = self._preferred_safe_lane(analysis)
            events.append("current_lane_threatened")
        events = list(dict.fromkeys(events))
        self.last_events = events
        self.previous_analysis = analysis
        return events, target_lane

    def record_action(
        self,
        analysis: dict[str, Any],
        action: str,
        step: int,
    ) -> None:
        key = _state_key(analysis)
        action_counts = self.state_action_bank.setdefault(key, {})
        counts = action_counts.setdefault(
            action, {"attempted": 0, "verified": 0, "failed": 0, "uncertain": 0}
        )
        counts["attempted"] += 1
        self.pending_action = {
            "action": action,
            "lane": analysis["player_lane"],
            "state_key": key,
            "hazards": sorted({
                item["type"] for item in analysis["obstacles"]
                if item["distance"] in {"mid", "near"}
            }),
        }
        for hazard in self.pending_action["hazards"]:
            by_action = self.knowledge_graph.setdefault(hazard, {})
            edge = by_action.setdefault(
                action, {"attempted": 0, "verified": 0, "failed": 0, "uncertain": 0}
            )
            edge["attempted"] += 1
        self.working_memory.append({
            "step": step,
            "lane": analysis["player_lane"],
            "action": action,
            "hazards": self.pending_action["hazards"],
        })
        del self.working_memory[:-8]

    def _verify_pending(
        self,
        analysis: dict[str, Any],
        verification: dict[str, str],
    ) -> str:
        pending = self.pending_action
        if pending is None:
            return "not_applicable"
        status = verification["status"]
        action = pending["action"]
        if action in {"left", "right"}:
            lane_index = _LANES.index(pending["lane"])
            target_index = lane_index + (-1 if action == "left" else 1)
            if 0 <= target_index < len(_LANES):
                if analysis["player_lane"] == _LANES[target_index]:
                    status = "verified"
                elif analysis["player_lane"] != pending["lane"]:
                    status = "failed"
                else:
                    status = "uncertain"
        if action == "wait":
            status = "verified"

        counts = self.state_action_bank[pending["state_key"]][action]
        counts[status if status in {"verified", "failed", "uncertain"} else "uncertain"] += 1
        for hazard in pending["hazards"]:
            edge = self.knowledge_graph[hazard][action]
            edge[status if status in {"verified", "failed", "uncertain"} else "uncertain"] += 1
        if self.working_memory:
            self.working_memory[-1]["verification"] = status
        self.pending_action = None
        return status

    def _preferred_safe_lane(
        self,
        analysis: dict[str, Any],
    ) -> str | None:
        lane = analysis["player_lane"]
        blocked = {
            item["lane"]
            for item in analysis["obstacles"]
            if item["distance"] in {"mid", "near"}
        }
        candidates = [
            target for target in _LANES
            if target != lane and target not in blocked
        ]
        if not candidates:
            return None
        action_names = {
            target: ("left" if _LANES.index(target) < _LANES.index(lane) else "right")
            for target in candidates
        }
        key = _state_key(analysis)

        def score(target: str) -> tuple[float, int]:
            action = action_names[target]
            counts = self.state_action_bank.get(key, {}).get(action, {})
            attempts = counts.get("attempted", 0)
            if not attempts:
                hazards = {
                    item["type"]
                    for item in analysis["obstacles"]
                    if item["distance"] in {"mid", "near"}
                }
                counts = {
                    name: sum(
                        self.knowledge_graph.get(hazard, {}).get(action, {}).get(name, 0)
                        for hazard in hazards
                    )
                    for name in ("attempted", "verified")
                }
                attempts = counts["attempted"]
            success_rate = counts.get("verified", 0) / attempts if attempts else 0
            return success_rate, -_LANES.index(target)

        return max(candidates, key=score)

    def preferred_escape_action(
        self,
        analysis: dict[str, Any],
        target_lane: str | None = None,
    ) -> str | None:
        target = target_lane or self._preferred_safe_lane(analysis)
        if target is None:
            return None
        return "left" if _LANES.index(target) < _LANES.index(analysis["player_lane"]) else "right"

    def _compact_graph(self) -> dict[str, Any]:
        return {
            hazard: actions
            for hazard, actions in list(self.knowledge_graph.items())[-6:]
        }

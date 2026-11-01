"""Data-driven HUD state transitions and cross-process reload signalling."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable

STATE_NAMES = frozenset(
    {"idle", "listening", "thinking", "speaking", "error", "generating_3d"}
)
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_STATE_FIELDS = {
    "core_color",
    "ring_speed",
    "waveform_amplitude",
    "glow_intensity",
    "particle_count",
}
_LIMITS = {
    "ring_speed": (0.0, 5.0),
    "waveform_amplitude": (0.0, 3.0),
    "glow_intensity": (0.0, 3.0),
    "particle_count": (0.0, 100.0),
}
_DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return number


def load_configuration(config_dir: Path | str | None = None) -> tuple[dict, dict]:
    """Load and validate both HUD JSON files; invalid data never replaces active settings."""
    folder = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
    try:
        states_data = json.loads((folder / "hud_states.json").read_text(encoding="utf-8"))
        transitions_data = json.loads(
            (folder / "hud_transitions.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read HUD configuration: {exc}") from exc

    raw_states = states_data.get("states") if isinstance(states_data, dict) else None
    if not isinstance(raw_states, dict) or set(raw_states) != STATE_NAMES:
        raise ValueError("hud_states.json must define exactly the six supported states")
    states = {}
    for state_name, raw in raw_states.items():
        if not isinstance(raw, dict) or set(raw) != _STATE_FIELDS:
            raise ValueError(f"{state_name} must define exactly: {', '.join(sorted(_STATE_FIELDS))}")
        color = raw["core_color"]
        if not isinstance(color, str) or not _COLOR_RE.fullmatch(color):
            raise ValueError(f"{state_name}.core_color must be a #RRGGBB color")
        state = {"core_color": color.lower()}
        for field, (low, high) in _LIMITS.items():
            value = _number(raw[field], f"{state_name}.{field}", low, high)
            if field == "particle_count" and not value.is_integer():
                raise ValueError(f"{state_name}.particle_count must be an integer")
            state[field] = int(value) if field == "particle_count" else value
        states[state_name] = state

    if not isinstance(transitions_data, dict):
        raise ValueError("hud_transitions.json must be an object")
    default_duration = _number(
        transitions_data.get("default_duration"), "default_duration", 0.0, 5.0
    )
    raw_transitions = transitions_data.get("transitions")
    if not isinstance(raw_transitions, dict):
        raise ValueError("hud_transitions.json.transitions must be an object")
    transitions = {}
    for key, value in raw_transitions.items():
        parts = key.split("->") if isinstance(key, str) else []
        if len(parts) != 2 or any(part not in STATE_NAMES for part in parts):
            raise ValueError(f"invalid HUD transition key: {key!r}")
        transitions[key] = _number(value, f"transition {key}", 0.0, 5.0)
    return states, {"default_duration": default_duration, "transitions": transitions}


def reload_signal_path(config_dir: Path | str | None = None) -> Path:
    folder = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
    digest = hashlib.sha256(str(folder.resolve()).encode("utf-8")).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"jarvis-hud-reload-{digest}.signal"


def request_reload(config_dir: Path | str | None = None) -> str:
    """Atomically notify running Jarvis instances to reload the selected config directory."""
    signal = reload_signal_path(config_dir)
    signal.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = signal.with_name(f"{signal.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(token, encoding="ascii")
        temporary.replace(signal)
    finally:
        temporary.unlink(missing_ok=True)
    return token


def _blend_color(start: str, end: str, amount: float) -> str:
    channels = []
    for offset in (1, 3, 5):
        left = int(start[offset:offset + 2], 16)
        right = int(end[offset:offset + 2], 16)
        channels.append(round(left + (right - left) * amount))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


class HudAnimator:
    """Interpolate validated HUD state data and pick up reload signals from the CLI."""

    def __init__(
        self,
        config_dir: Path | str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.config_dir = Path(config_dir) if config_dir is not None else _DEFAULT_CONFIG_DIR
        self._clock = clock
        self.states, self.transitions = load_configuration(self.config_dir)
        self.state = "idle"
        self._started = self._clock()
        self._duration = 0.0
        self._source = dict(self.states[self.state])
        self._target = dict(self._source)
        self._last_poll = float("-inf")
        self._reload_token = self._read_reload_token()

    def _read_reload_token(self) -> str | None:
        try:
            return reload_signal_path(self.config_dir).read_text(encoding="ascii")
        except FileNotFoundError:
            return None

    def set_state(self, state_name: str, now: float | None = None) -> dict:
        normalized = str(state_name).strip().lower()
        if normalized not in self.states:
            raise ValueError(f"Unsupported HUD state: {state_name}")
        current_time = self._clock() if now is None else now
        previous_state = self.state
        self._source = self.update(current_time, _allow_reload=False)
        self.state = normalized
        self._target = dict(self.states[normalized])
        key = f"{previous_state}->{normalized}"
        self._duration = self.transitions["transitions"].get(
            key, self.transitions["default_duration"]
        )
        self._started = current_time
        return self.target_snapshot()

    def target_snapshot(self) -> dict:
        return {
            "state": self.state,
            **self._target,
            "transition_seconds": self._duration,
        }

    def update(self, now: float | None = None, _allow_reload: bool = True) -> dict:
        current_time = self._clock() if now is None else now
        if _allow_reload:
            self.poll_reload(current_time)
        amount = (
            1.0 if self._duration <= 0
            else min(1.0, max(0.0, (current_time - self._started) / self._duration))
        )
        eased = amount * amount * (3.0 - 2.0 * amount)
        result = {"state": self.state}
        for field in _STATE_FIELDS:
            start, end = self._source[field], self._target[field]
            if field == "core_color":
                result[field] = _blend_color(start, end, eased)
            else:
                value = float(start) + (float(end) - float(start)) * eased
                result[field] = round(value) if field == "particle_count" else value
        result["target_core_color"] = self._target["core_color"]
        result["transition_seconds"] = self._duration
        return result

    def reload(self, now: float | None = None) -> dict:
        states, transitions = load_configuration(self.config_dir)
        self.states = states
        self.transitions = transitions
        return self.set_state(self.state, now)

    def poll_reload(self, now: float | None = None) -> bool:
        current_time = self._clock() if now is None else now
        if current_time - self._last_poll < 0.25:
            return False
        self._last_poll = current_time
        token = self._read_reload_token()
        if token is None or token == self._reload_token:
            return False
        self.reload(current_time)
        self._reload_token = token
        return True

"""Screen capture and injectable OCR/CV parsing for Subway Surfers."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Mapping

Lane = Literal["left", "center", "right"]
Distance = Literal["near", "mid", "far"]
Hazard = Literal["train", "barrier", "low_barrier", "gap", "overhead", "unknown"]

_LANES = {"left", "center", "right"}
_DISTANCES = {"near", "mid", "far"}
_HAZARDS = {"train", "barrier", "low_barrier", "gap", "overhead", "unknown"}


@dataclass(frozen=True)
class GameObstacle:
    lane: Lane
    kind: Hazard
    distance: Distance = "near"

    def __post_init__(self) -> None:
        if self.lane not in _LANES:
            raise ValueError(f"Unknown game lane: {self.lane!r}.")
        if self.kind not in _HAZARDS:
            raise ValueError(f"Unknown obstacle type: {self.kind!r}.")
        if self.distance not in _DISTANCES:
            raise ValueError(f"Unknown obstacle distance: {self.distance!r}.")


@dataclass(frozen=True)
class GameState:
    score: int | None = None
    lane: Lane | None = None
    obstacles: tuple[GameObstacle, ...] = ()
    crashed: bool = False
    active: bool = True
    raw_text: str = ""
    captured_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds")
    )

    def __post_init__(self) -> None:
        if self.score is not None and (
            isinstance(self.score, bool) or not isinstance(self.score, int) or self.score < 0
        ):
            raise ValueError("score must be a non-negative integer or None.")
        if self.lane is not None and self.lane not in _LANES:
            raise ValueError(f"Unknown game lane: {self.lane!r}.")
        if not isinstance(self.obstacles, tuple) or any(
            not isinstance(item, GameObstacle) for item in self.obstacles
        ):
            raise TypeError("obstacles must be a tuple of GameObstacle values.")
        if not isinstance(self.crashed, bool) or not isinstance(self.active, bool):
            raise TypeError("crashed and active must be booleans.")


FrameProvider = Callable[[], bytes]
FrameAnalyzer = Callable[[bytes], GameState | Mapping[str, Any] | str]


def _capture_screen() -> bytes:
    try:
        import pyautogui
    except ImportError as exc:
        raise RuntimeError(
            "Screen capture requires PyAutoGUI; install it or inject a frame_provider."
        ) from exc
    image = pyautogui.screenshot()
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _ocr_png(frame: bytes) -> str:
    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "Default OCR requires Pillow and pytesseract; install them or inject "
            "a frame_analyzer."
        ) from exc
    try:
        with Image.open(io.BytesIO(frame)) as image:
            return str(pytesseract.image_to_string(image))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not decode the captured game frame: {exc}") from exc


def parse_game_text(text: str) -> GameState:
    """Extract conservative HUD facts from OCR text; CV analyzers can be injected."""
    if not isinstance(text, str):
        raise TypeError("OCR output must be text.")
    normalized = text.casefold()
    score_match = re.search(r"\b(?:score|punteggio)\s*[:#]?\s*([\d,.\s]{1,16})", text, re.I)
    score = None
    if score_match:
        digits = re.sub(r"\D", "", score_match.group(1))
        if digits:
            score = int(digits)

    lane = next(
        (
            candidate
            for candidate, patterns in (
                ("left", (r"\bleft lane\b", r"\bcorsia sinistra\b")),
                ("center", (r"\bcenter lane\b", r"\bmiddle lane\b", r"\bcorsia centrale\b")),
                ("right", (r"\bright lane\b", r"\bcorsia destra\b")),
            )
            if any(re.search(pattern, normalized) for pattern in patterns)
        ),
        None,
    )
    crashed = any(
        phrase in normalized
        for phrase in ("game over", "crashed", "crash!", "fine della partita")
    )

    obstacles: list[GameObstacle] = []
    lane_pattern = {
        "left": r"\bleft\b|\bsinistr[oa]\b",
        "center": r"\bcenter\b|\bmiddle\b|\bcentral[ea]\b",
        "right": r"\bright\b|\bdestr[oa]\b",
    }
    hazard_patterns = (
        ("low_barrier", r"low barrier|barriera bassa"),
        ("overhead", r"overhead|above|sopra la testa"),
        ("train", r"\btrain\b|\btreno\b"),
        ("barrier", r"\bbarrier\b|\bbarriera\b"),
        ("gap", r"\bgap\b|\bvuoto\b|\bbuca\b"),
    )
    for line in normalized.splitlines():
        kind = next(
            (name for name, pattern in hazard_patterns if re.search(pattern, line)),
            None,
        )
        lane_name = next(
            (name for name, pattern in lane_pattern.items() if re.search(pattern, line)),
            None,
        )
        if kind and lane_name:
            obstacles.append(GameObstacle(lane_name, kind))

    return GameState(
        score=score,
        lane=lane,
        obstacles=tuple(obstacles[:30]),
        crashed=crashed,
        active=not crashed,
        raw_text=text[:5000],
    )


class GameVision:
    """Capture a frame and convert it into a validated :class:`GameState`.

    The default path uses a desktop screenshot and OCR. Supply a frame analyzer
    for CV/ML obstacle detection; both capture and analysis are injectable for
    deterministic tests and platform-specific integrations.
    """

    def __init__(
        self,
        frame_provider: FrameProvider | None = None,
        frame_analyzer: FrameAnalyzer | None = None,
    ) -> None:
        self.frame_provider = frame_provider or _capture_screen
        self.frame_analyzer = frame_analyzer or _ocr_png

    def perceive(self) -> GameState:
        frame = self.frame_provider()
        if not isinstance(frame, bytes) or not frame:
            raise RuntimeError("The screen provider returned an empty or invalid frame.")
        analyzed = self.frame_analyzer(frame)
        if isinstance(analyzed, GameState):
            return analyzed
        if isinstance(analyzed, str):
            return parse_game_text(analyzed)
        if isinstance(analyzed, Mapping):
            try:
                obstacles = tuple(
                    item
                    if isinstance(item, GameObstacle)
                    else GameObstacle(**item)
                    for item in analyzed.get("obstacles", ())
                )
                return GameState(
                    score=analyzed.get("score"),
                    lane=analyzed.get("lane"),
                    obstacles=obstacles,
                    crashed=analyzed.get("crashed", False),
                    active=analyzed.get("active", not analyzed.get("crashed", False)),
                    raw_text=str(analyzed.get("raw_text", ""))[:5000],
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Frame analyzer returned an invalid game state: {exc}") from exc
        raise TypeError("frame_analyzer must return GameState, a mapping, or OCR text.")

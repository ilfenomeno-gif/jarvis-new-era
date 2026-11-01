"""Small, local learner for repeated 3D preferences and corrections."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

PATTERNS_PATH = Path(__file__).resolve().parent.parent / "memory" / "learned_patterns.json"
ENABLED_ENV = "JARVIS_PATTERN_LEARNER"
PATTERN_TYPES = frozenset({"style_preference", "tool_failure", "correction", "app_launch"})
STYLES = frozenset({"blueprint", "realistic", "toon", "flat", "hologram"})
MAX_PATTERNS = 100
MAX_HINTS = 3
MAX_HINT_CHARS = 200
HINT_HEADER = "[LEARNED PREFERENCES]\n"

_lock = threading.RLock()
_CONTEXTS = {
    "auto": re.compile(r"\b(auto|macchina|macchine|automobile|automobili|car|cars|vehicle|vehicles)\b", re.I),
    "sedia": re.compile(r"\b(sedia|sedie|chair|chairs)\b", re.I),
    "mela": re.compile(r"\b(mela|mele|apple|apples)\b", re.I),
    "pc": re.compile(r"\b(pc|computer|personal computer)\b", re.I),
}
_CORRECTION = re.compile(
    r"\b(no|rifai|rifallo|riprova|sbagliat\w*|non va|non mi piace|non è corretto|cambia)\b",
    re.I,
)
_STYLE_ALIASES = {
    "blueprint": "blueprint",
    "realistic": "realistic",
    "realistica": "realistic",
    "realistico": "realistic",
    "toon": "toon",
    "cartoon": "toon",
    "flat": "flat",
    "hologram": "hologram",
}
_STYLE_PATTERN = re.compile(
    r"preferred:([a-z]+);previous:([a-z]+)", re.I
)
_MODEL_PATH = re.compile(r"(?:^|[/\\])([^/\\]+)\.(?:glb|gltf)$", re.I)
_SAFE_CONTEXT = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}\Z")
_SAFE_APP_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "1").strip() != "0"


def context_for(text: str | None) -> str:
    value = str(text or "")
    for context, pattern in _CONTEXTS.items():
        if pattern.search(value):
            return context
    return "general"


def model_context_for(text: str | None) -> str:
    value = str(text or "").strip()
    model_path = _MODEL_PATH.search(value)
    if model_path:
        model_name = model_path.group(1).casefold()
        return model_name if _SAFE_CONTEXT.fullmatch(model_name) else "3d"
    context = context_for(text)
    return "3d" if context == "general" else context


def style_for_text(text: str | None) -> str | None:
    words = re.findall(r"[a-z]+", str(text or "").casefold())
    return next((_STYLE_ALIASES[word] for word in words if word in _STYLE_ALIASES), None)


def _normalize_context(value: str | None) -> str:
    context = str(value or "").strip().casefold()
    if context in {*_CONTEXTS, "3d", "general"}:
        return context
    inferred = context_for(context)
    if inferred != "general":
        return inferred
    if _SAFE_CONTEXT.fullmatch(context):
        return context
    return inferred


def _normalize_observation(pattern_type: str, observation: str) -> str:
    if pattern_type == "style_preference":
        match = _STYLE_PATTERN.fullmatch(str(observation or "").strip())
        if not match:
            raise ValueError("Style observations must use preferred:<style>;previous:<style>")
        preferred, previous = (item.casefold() for item in match.groups())
        if preferred not in STYLES or (previous not in STYLES and previous not in {"none", "unknown"}):
            raise ValueError("Unsupported style in pattern observation")
        return f"preferred:{preferred};previous:{previous}"
    if pattern_type == "tool_failure":
        return "fallback:generate_3d_model"
    if pattern_type == "correction":
        return "corrected_output"
    if pattern_type == "app_launch":
        normalized = str(observation or "").strip().casefold()
        if not _SAFE_APP_NAME.fullmatch(normalized):
            raise ValueError("App launch observations must use a safe application identifier")
        return normalized
    raise ValueError(f"Unsupported pattern type: {pattern_type}")


def _pattern_id(pattern_type: str, context: str, observation: str) -> str:
    identity_observation = observation
    if pattern_type == "style_preference":
        match = _STYLE_PATTERN.fullmatch(observation)
        if match is not None:
            identity_observation = f"preferred:{match.group(1).casefold()}"
    payload = "\0".join((pattern_type, context, identity_observation)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _load_patterns() -> list[dict]:
    if not PATTERNS_PATH.exists():
        return []
    data = json.loads(PATTERNS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), list):
        raise ValueError("learned_patterns.json must contain a patterns list")

    patterns = []
    for item in data["patterns"]:
        if not isinstance(item, dict):
            raise ValueError("Each learned pattern must be an object")
        pattern_type = str(item.get("type") or "")
        if pattern_type not in PATTERN_TYPES:
            raise ValueError("learned_patterns.json contains an unknown pattern type")
        context = _normalize_context(item.get("context"))
        observation = _normalize_observation(pattern_type, str(item.get("observation") or ""))
        occurrences = item.get("occurrences")
        confidence = item.get("confidence")
        last_seen = item.get("last_seen")
        if (
            not isinstance(occurrences, int)
            or isinstance(occurrences, bool)
            or occurrences < 1
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1
            or not isinstance(last_seen, str)
        ):
            raise ValueError("learned_patterns.json contains invalid pattern metadata")
        patterns.append({
            "id": _pattern_id(pattern_type, context, observation),
            "type": pattern_type,
            "context": context,
            "observation": observation,
            "confidence": float(confidence),
            "occurrences": occurrences,
            "last_seen": last_seen,
        })
    return patterns


def _save_patterns(patterns: list[dict]) -> None:
    PATTERNS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=".learned-patterns-", suffix=".tmp", dir=PATTERNS_PATH.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"patterns": patterns}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, PATTERNS_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def extract_patterns(observations: list[dict] | dict) -> list[dict]:
    """Aggregate repeated, normalized observations into persistent patterns."""
    if not enabled():
        return []
    items = [observations] if isinstance(observations, dict) else observations
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Pattern observations must be objects")
        pattern_type = str(item.get("type") or "")
        if pattern_type not in PATTERN_TYPES:
            raise ValueError(f"Unsupported pattern type: {pattern_type}")
        context = _normalize_context(item.get("context"))
        observation = _normalize_observation(pattern_type, str(item.get("observation") or ""))
        normalized.append((pattern_type, context, observation))

    if not normalized:
        return []
    with _lock:
        patterns = _load_patterns()
        by_id = {pattern["id"]: pattern for pattern in patterns}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        updated = []
        for pattern_type, context, observation in normalized:
            pattern_id = _pattern_id(pattern_type, context, observation)
            pattern = by_id.get(pattern_id)
            if pattern is None:
                pattern = {
                    "id": pattern_id,
                    "type": pattern_type,
                    "context": context,
                    "observation": observation,
                    "confidence": 0.3,
                    "occurrences": 0,
                    "last_seen": now,
                }
                patterns.append(pattern)
                by_id[pattern_id] = pattern
            pattern["occurrences"] = min(10000, pattern["occurrences"] + 1)
            pattern["confidence"] = round(min(0.99, pattern["occurrences"] * 0.3), 2)
            pattern["last_seen"] = now
            updated.append(pattern.copy())

        if len(patterns) > MAX_PATTERNS:
            patterns.sort(key=lambda pattern: (pattern["confidence"], pattern["last_seen"]))
            patterns = patterns[-MAX_PATTERNS:]
        _save_patterns(patterns)
        return updated


def observe(pattern_type: str, context: str, observation: str) -> list[dict]:
    return extract_patterns({
        "type": pattern_type,
        "context": context,
        "observation": observation,
    })


def observe_style_preference(
    context: str,
    preferred_style: str,
    previous_style: str | None = None,
) -> list[dict]:
    preferred = str(preferred_style or "").casefold()
    previous = str(previous_style).casefold() if previous_style else "none"
    if preferred not in STYLES or (previous not in STYLES and previous not in {"none", "unknown"}):
        return []
    return observe(
        "style_preference",
        context,
        f"preferred:{preferred};previous:{previous}",
    )


def observe_tool_failure(context: str) -> list[dict]:
    return observe("tool_failure", context, "fallback:generate_3d_model")


def observe_app_launch(context: str, app_name: str) -> list[dict]:
    identifier = re.sub(r"[^a-z0-9._-]+", "", str(app_name or "").casefold())
    if not identifier or not _SAFE_APP_NAME.fullmatch(identifier):
        return []
    return observe("app_launch", context, identifier)


def observe_correction(
    context: str,
    text: str,
    previous_style: str | None = None,
) -> list[dict]:
    if not enabled() or not _CORRECTION.search(str(text or "")):
        return []
    observations = [{
        "type": "correction",
        "context": context,
        "observation": "corrected_output",
    }]
    preferred = style_for_text(text)
    previous = str(previous_style or "unknown").casefold()
    if preferred:
        observations.append({
            "type": "style_preference",
            "context": context,
            "observation": f"preferred:{preferred};previous:{previous}",
        })
    return extract_patterns(observations)


def list_patterns() -> list[dict]:
    with _lock:
        return sorted(_load_patterns(), key=lambda item: item["last_seen"], reverse=True)


def delete_pattern(pattern_id: str) -> bool:
    with _lock:
        patterns = _load_patterns()
        remaining = [pattern for pattern in patterns if pattern["id"] != str(pattern_id)]
        if len(remaining) == len(patterns):
            return False
        _save_patterns(remaining)
        return True


def clear() -> int:
    with _lock:
        count = len(_load_patterns())
        _save_patterns([])
        return count


def _hint_for(pattern: dict) -> str:
    context = pattern["context"]
    if pattern["type"] == "app_launch":
        if context == "general":
            return f"Frequently launched application: {pattern['observation']}."
        return f"For {context}, frequently launched application: {pattern['observation']}."
    if pattern["type"] == "style_preference":
        match = _STYLE_PATTERN.fullmatch(pattern["observation"])
        if match is None:
            return ""
        preferred, previous = match.groups()
        subject = "3D models" if context == "3d" else f"{context} models"
        if previous in {"none", "unknown"}:
            return f"For {subject}, prefer {preferred} style."
        return f"For {subject}, prefer {preferred} over {previous}."
    if pattern["type"] == "tool_failure":
        subject = "3D models" if context == "3d" else f"{context} models"
        return f"For {context} models, skip repeated searches and use generate_3d_model."
    if context == "general":
        return "After a correction, incorporate it before repeating the answer."
    subject = "3D models" if context == "3d" else f"{context} models"
    return f"For {subject}, apply corrections before repeating an output."


def get_hints_for(current_context: str | None = None) -> str:
    if not enabled():
        return ""
    context = _normalize_context(current_context) if current_context else None
    type_order = {"style_preference": 0, "tool_failure": 1, "correction": 2, "app_launch": 3}
    patterns = [
        item for item in list_patterns()
        if item["confidence"] >= 0.7
        and (context is None or item["context"] in {context, "3d"})
    ]
    patterns.sort(key=lambda item: item["last_seen"], reverse=True)
    patterns.sort(key=lambda item: (-item["confidence"], type_order[item["type"]]))
    hints: list[str] = []
    hint_budget = MAX_HINT_CHARS - len(HINT_HEADER)
    for pattern in patterns:
        hint = _hint_for(pattern)
        candidate = " | ".join((*hints, hint)) if hint else ""
        if hint and hint not in hints and len(hints) < MAX_HINTS and len(candidate) <= hint_budget:
            hints.append(hint)
    return " | ".join(hints)


def add_hints_to_prompt(prompt: str, current_context: str | None = None) -> str:
    hints = get_hints_for(current_context)
    if not hints:
        return prompt
    return f"{HINT_HEADER}{hints}\n\n{prompt}"

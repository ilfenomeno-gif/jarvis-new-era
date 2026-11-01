from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from actions.game_updater import _KNOWN_APPIDS
from memory.memory_manager import load_memory, update_memory

_GAME_WORDS = re.compile(r"\b(gioco|giochi|game|games|steam|epic|launcher|videogioco|videogame)\b", re.I)
_FILE_WORDS = re.compile(r"\b(file|cartella|directory|documento|document|pdf|immagine|foto|testo|txt|csv|excel|word)\b", re.I)
_OPEN_WORDS = re.compile(r"\b(apri|aprimi|avvia|avvii|lancia|launch|open|start|cerca|trova)\b", re.I)
_GAME_ALIASES = {"victoria", "v3"}
_GEO_QUERY_WORDS = re.compile(
    r"\b(dove|mappa|posizione|coordinate|localizza|geografia)\b|dov['’](?:e|è)",
    re.I,
)
_HISTORY_QUERY_WORDS = re.compile(
    r"\b(storia|storico|storica|battaglia|guerra|assedio|rivoluzione|"
    r"impero|antichità|medioevo|rinascimento|epoca|chi era|"
    r"quando è avvenut[oa])\b",
    re.I,
)


def classify_geo_history_intent(query: str) -> str:
    """Classify explicit geography/history phrasing without routing guesses."""
    query = query or ""
    if _HISTORY_QUERY_WORDS.search(query):
        return "history"
    if _GEO_QUERY_WORDS.search(query):
        return "geo"
    return "none"


@dataclass(frozen=True)
class IntentDecision:
    category: str
    target: str
    launcher: str = ""
    clarification: str = ""

    @property
    def blocked(self) -> bool:
        return self.category == "ambiguous"


def _remembered_category(target: str) -> tuple[str, str]:
    key = _memory_key(target)
    memory = load_memory()
    entry = memory.get("notes", {}).get(f"target_intent_{key}", {})
    value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
    if value.startswith("game:"):
        return "game", value.split(":", 1)[1]
    if value == "file":
        return "file", ""
    return "", ""


def _memory_key(target: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", target.casefold()).strip("_")
    return key[:60] or "unknown"


def _save_association(target: str, category: str, launcher: str = "") -> None:
    value = f"{category}:{launcher}" if launcher else category
    update_memory({"notes": {f"target_intent_{_memory_key(target)}": {"value": value}}})


def remember_explicit_intent(request: str, target: str) -> None:
    """Persist only an explicit user category, never a model guess."""
    if not target:
        return
    if _GAME_WORDS.search(request or ""):
        _save_association(target, "game", "steam" if re.search(r"\bsteam\b", request, re.I) else "launcher")
    elif _FILE_WORDS.search(request or ""):
        _save_association(target, "file")


def classify_target(target: str, request: str = "") -> IntentDecision:
    target = (target or "").strip()
    request = request or ""
    if not target:
        return IntentDecision("unknown", target)

    remembered, launcher = _remembered_category(target)
    explicit_game = bool(_GAME_WORDS.search(request))
    explicit_file = bool(_FILE_WORDS.search(request))
    target_key = target.casefold()
    exact_game = target_key in _KNOWN_APPIDS
    partial_game = (
        any(target_key in name or name in target_key for name in _KNOWN_APPIDS)
        or target_key in _GAME_ALIASES
    )
    path_like = bool(Path(target).suffix) or any(token in target for token in ("\\", "/", ":"))

    if explicit_game or remembered == "game" or exact_game:
        requested_launcher = (
            "steam" if re.search(r"\bsteam\b", request, re.I)
            else "epic" if re.search(r"\bepic\b", request, re.I)
            else ""
        )
        return IntentDecision(
            "game", target,
            requested_launcher or launcher or ("steam" if exact_game else "launcher"),
        )
    if explicit_file or remembered == "file" or path_like:
        return IntentDecision("file", target)
    if partial_game or (explicit_game and explicit_file):
        return IntentDecision("ambiguous", target, clarification=(
            f"Signore, intende il gioco '{target}' tramite Steam/Epic oppure un file locale?"
        ))
    return IntentDecision("unknown", target)


def route_tool(name: str, args: dict, request: str = "") -> IntentDecision | None:
    """Return a blocking decision only when a target must be clarified."""
    target = (args.get("game_name") or args.get("app_name") or args.get("name")
              or args.get("file_path") or args.get("query")
              or args.get("instruction") or "").strip()
    request_key = request.casefold()
    request_game = next(
        (name for name in (*_KNOWN_APPIDS.keys(), *_GAME_ALIASES) if name in request_key),
        "",
    )
    if request_game and name in {"file_processor", "file_controller", "web_search"}:
        target = request_game
    if not target:
        return None
    decision = classify_target(target, request)
    if request:
        remember_explicit_intent(request, target)
    if name in {"open_app", "app_launcher", "game_updater", "file_processor", "file_controller", "web_search"}:
        if decision.category == "ambiguous":
            return decision
        if decision.category == "game" and name == "app_launcher":
            return IntentDecision("ambiguous", target, clarification=(
                f"Signore, '{target}' sembra un gioco. Desidera avviarlo tramite Steam/Epic?"
            ))
        if decision.category == "game" and name in {"file_processor", "file_controller", "web_search"}:
            return IntentDecision("ambiguous", target, clarification=(
                f"Signore, '{target}' sembra un gioco. Desidera avviarlo tramite Steam/Epic?"
            ))
        if decision.category == "file" and name in {"open_app", "game_updater"}:
            return IntentDecision("ambiguous", target, clarification=(
                f"Signore, '{target}' sembra un file locale. Desidera aprire il documento o un'applicazione?"
            ))
    return decision

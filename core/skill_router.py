"""Two-axis router: intent (creative vs technical) first, then which skill."""
from __future__ import annotations

import re
from dataclasses import dataclass

from core.connectors import ConnectorRegistry
from core.skills import Activation, SkillRegistry

_CREATIVE = ("scrivi", "racconto", "storia", "poesia", "immagine", "disegna", "design",
             "write a story", "poem", "creative", "canzone", "video")
_TECHNICAL = ("codice", "bug", "errore", "script", "debug", "commit", "test", "api",
              "code", "function", "build", "deploy")
_STOP = {"quando", "della", "delle", "degli", "questa", "skill", "usa", "non", "usarla",
         "come", "che", "per", "con", "una", "the", "and", "for", "use", "when"}


def classify_intent(text: str) -> str:
    lowered = text.lower()
    creative = sum(word in lowered for word in _CREATIVE)
    technical = sum(word in lowered for word in _TECHNICAL)
    if creative == technical:
        return "general"
    return "creative" if creative > technical else "technical"


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zà-ú]{4,}", text.lower()) if w not in _STOP}


@dataclass
class Route:
    intent: str
    skill: str | None
    score: int


class SkillRouter:
    def __init__(self, skills: SkillRegistry, connectors: ConnectorRegistry | None = None) -> None:
        self._skills = skills
        self._connectors = connectors

    def route(self, text: str) -> Route:
        intent = classify_intent(text)
        lowered = text.lower()
        words = _words(text)
        best, best_score = None, 0
        for skill in self._skills.active():
            score = 10 * sum(t.lower() in lowered for t in skill.triggers)
            if score == 0:
                score = len(words & _words(skill.description)) // 2
            if score > best_score:
                best, best_score = skill.name, score
        return Route(intent, best, best_score)

    def prepare(self, text: str) -> tuple[Route, Activation | None]:
        """Route, then load the body and verify connectors only for the chosen skill."""
        route = self.route(text)
        if route.skill is None:
            return route, None
        return route, self._skills.activate(route.skill, self._connectors)

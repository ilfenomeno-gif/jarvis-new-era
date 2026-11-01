from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROMPT_REPOSITORY_URL = "https://github.com/ilfenomeno-gif/repo-prompt"


@dataclass(frozen=True)
class PromptProfile:
    mode: str
    rules: str
    thinking_level: str = "high"


class PromptRouter:
    """Select a small task profile without exposing private chain-of-thought."""

    _MODE_RULES = {
        "developer_mode": """Use precise engineering reasoning. Inspect relevant context, state assumptions, and propose or execute the smallest testable change. Do not expose hidden chain-of-thought; provide conclusions and concise reasons.""",
        "strategic_mode": """Use contextual planning and verify constraints before acting. Distinguish games/apps from local files, prefer the correct launcher, and ask formally when ambiguous. Do not expose hidden chain-of-thought.""",
        "quick_command": """Handle this as a short command. Use the correct tool once, report the observable result, and do not add speculative explanation.""",
        "standard_assistant": """Handle the request contextually and formally. Select the correct tool, avoid guessing, and report only verified results.""",
    }

    _KEYWORDS = {
        "developer_mode": {"codice", "code", "debug", "script", "python", "errore", "refactor", "compile", "test"},
        "strategic_mode": {"strategia", "strategy", "gioco", "game", "analizza", "analisi", "piano", "simula", "confronta"},
    }

    def __init__(self, prompts_path: Path | None = None, repository_url: str = PROMPT_REPOSITORY_URL):
        self.prompts_path = prompts_path or Path(__file__).resolve().parent / "prompts"
        self.repository_url = repository_url

    def classify(self, user_text: str) -> str:
        words = set(user_text.casefold().split())
        for mode in ("developer_mode", "strategic_mode"):
            if words.intersection(self._KEYWORDS[mode]):
                return mode
        if len(words) <= 3:
            return "quick_command"
        return "standard_assistant"

    def load(self, mode: str) -> PromptProfile:
        fallback = self._MODE_RULES.get(mode, self._MODE_RULES["standard_assistant"])
        path = self.prompts_path / f"{mode}.txt"
        try:
            rules = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            rules = fallback
        resolved_mode = mode if mode in self._MODE_RULES else "standard_assistant"
        thinking_level = "low" if resolved_mode == "quick_command" else "high"
        return PromptProfile(resolved_mode, rules or fallback, thinking_level)

    def profile_for(self, user_text: str) -> PromptProfile:
        return self.load(self.classify(user_text))

    def thinking_level_for(self, user_text: str) -> str:
        return self.profile_for(user_text).thinking_level

    def instruction_for(self, user_text: str) -> str:
        profile = self.profile_for(user_text)
        return (
            f"[DYNAMIC_TASK_PROFILE mode={profile.mode}]\n"
            f"{profile.rules}\n"
            "Apply the existing formal-language, intent-routing, memory, and security rules."
        )

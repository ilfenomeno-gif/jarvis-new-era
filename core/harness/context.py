from __future__ import annotations

from typing import Any

from core.harness.session import HarnessSession


class ContextAssembler:
    def __init__(
        self,
        *,
        max_context_tokens: int = 32_000,
        compaction_ratio: float = 0.75,
        max_history_messages: int = 20,
        system_prompt: str = "You are Jarvis, an AI assistant.",
    ) -> None:
        if max_context_tokens < 1:
            raise ValueError("max_context_tokens must be positive.")
        if not 0 < compaction_ratio <= 1:
            raise ValueError("compaction_ratio must be in (0, 1].")
        if max_history_messages < 0:
            raise ValueError("max_history_messages cannot be negative.")
        self.max_context_tokens = max_context_tokens
        self.compaction_ratio = compaction_ratio
        self.max_history_messages = max_history_messages
        self.system_prompt = system_prompt

    @staticmethod
    def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
        return sum((len(str(message.get("content", ""))) + 3) // 4 for message in messages)

    def build(self, session: HarnessSession, policy: dict[str, Any]) -> list[dict[str, str]]:
        system = policy.get("system_prompt", self.system_prompt)
        messages = [{"role": "system", "content": str(system)}]
        history = session.history[-self.max_history_messages:] if self.max_history_messages else []
        for item in history:
            if not isinstance(item, dict):
                continue
            role, content = item.get("role"), item.get("content")
            if isinstance(role, str) and isinstance(content, str):
                messages.append({"role": role, "content": content})
        last_content = history[-1].get("content") if history and isinstance(history[-1], dict) else None
        if last_content != session.goal:
            messages.append({"role": "user", "content": session.goal})
        return messages

    def should_compact(self, session: HarnessSession) -> bool:
        messages = [
            {"role": item.get("role", ""), "content": item.get("content", "")}
            for item in session.history
            if isinstance(item, dict)
        ]
        messages.append({"role": "user", "content": session.goal})
        threshold = self.max_context_tokens * self.compaction_ratio
        return self._estimate_tokens(messages) >= threshold

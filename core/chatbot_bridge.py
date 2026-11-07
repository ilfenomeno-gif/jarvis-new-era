"""Provider-neutral interface for chatbot adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence


class BaseChatbot(ABC):
    """Contract implemented by local mocks and future external API adapters."""

    def __init__(self, name: str) -> None:
        normalized = name.strip() if isinstance(name, str) else ""
        if not normalized or len(normalized) > 100:
            raise ValueError("Chatbot name must contain 1 to 100 characters.")
        self.name = normalized

    @abstractmethod
    def send_message(self, text: str) -> str:
        """Send a prompt and return the chatbot's response."""


class MockChatbot(BaseChatbot):
    """Deterministic chatbot adapter for tests and offline orchestration."""

    def __init__(
        self,
        name: str = "MockChatbot",
        responses: Sequence[str] | Callable[[str], str] | str | None = None,
    ) -> None:
        super().__init__(name)
        if responses is None:
            self._responses: Sequence[str] | Callable[[str], str] | str = (
                "Mock chatbot received the request."
            )
        elif isinstance(responses, str) or callable(responses):
            self._responses = responses
        elif isinstance(responses, Sequence) and not isinstance(responses, (bytes, bytearray)):
            if any(not isinstance(item, str) for item in responses):
                raise TypeError("Mock chatbot responses must be strings.")
            self._responses = tuple(responses)
        else:
            raise TypeError("responses must be text, a sequence of text, or a callable.")
        self.sent_messages: list[str] = []
        self._response_index = 0

    def send_message(self, text: str) -> str:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Chatbot message must be non-empty text.")
        self.sent_messages.append(text)
        if callable(self._responses):
            response = self._responses(text)
        elif isinstance(self._responses, str):
            response = self._responses
        else:
            if self._response_index >= len(self._responses):
                raise RuntimeError(f"Mock chatbot {self.name} has no more responses.")
            response = self._responses[self._response_index]
            self._response_index += 1
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError(f"Chatbot {self.name} returned an empty or invalid response.")
        return response.strip()

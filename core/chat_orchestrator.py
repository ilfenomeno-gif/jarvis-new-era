"""Persistent, source-attributed multi-turn conversations and content planning."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Mapping

from core.chatbot_bridge import BaseChatbot
from core.memory_store import MemoryStore

MessageSource = Literal["user", "chatbot", "jarvis"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _normalized_text(value: str, label: str, limit: int = 20_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text.")
    normalized = value.strip()
    if len(normalized) > limit:
        raise ValueError(f"{label} must not exceed {limit} characters.")
    return normalized


@dataclass(frozen=True)
class ChatMessage:
    turn_index: int
    source: MessageSource
    source_name: str | None
    text: str
    created_at: str


@dataclass(frozen=True)
class ChatbotSuggestion:
    chatbot_name: str
    text: str


@dataclass(frozen=True)
class ContentPlan:
    plan_id: str
    topic: str
    user_preferences: dict[str, Any]
    conversation_context: tuple[dict[str, Any], ...]
    key_points: tuple[str, ...]
    chatbot_suggestions: tuple[ChatbotSuggestion, ...]
    jarvis_synthesis: str
    outline: tuple[str, ...]
    created_at: str


class ChatOrchestrator:
    """Keep a durable attributed conversation and delegate planning to adapters."""

    def __init__(
        self,
        memory_store: MemoryStore | None = None,
        *,
        session_id: str | None = None,
        chatbots: Mapping[str, BaseChatbot] | None = None,
    ) -> None:
        if session_id is not None:
            session_id = _normalized_text(session_id, "session_id", limit=200)
        self.session_id = session_id or uuid.uuid4().hex
        self.memory_store = memory_store or MemoryStore()
        self.chatbots: dict[str, BaseChatbot] = {}
        for key, chatbot in (chatbots or {}).items():
            if not isinstance(chatbot, BaseChatbot):
                raise TypeError("Every chatbot must implement BaseChatbot.")
            normalized_key = _normalized_text(key, "chatbot key", limit=100)
            if normalized_key != chatbot.name:
                raise ValueError("Chatbot mapping keys must match each adapter's name.")
            self.chatbots[normalized_key] = chatbot

        stored = self.memory_store.recall(
            "session", self._session_memory_key(self.session_id)
        )
        if stored is None:
            self._messages: list[ChatMessage] = []
        else:
            if not isinstance(stored, dict) or stored.get("session_id") != self.session_id:
                raise ValueError(f"Stored conversation {self.session_id!r} is invalid.")
            raw_messages = stored.get("messages")
            if not isinstance(raw_messages, list):
                raise ValueError(f"Stored conversation {self.session_id!r} has no messages.")
            self._messages = [self._message_from_payload(item) for item in raw_messages]

    @staticmethod
    def _session_memory_key(session_id: str) -> str:
        return f"chat:{session_id}"

    @staticmethod
    def _message_from_payload(value: Any) -> ChatMessage:
        if not isinstance(value, dict):
            raise ValueError("Stored chat message must be an object.")
        source = value.get("source")
        source_name = value.get("source_name")
        if source not in {"user", "chatbot", "jarvis"}:
            raise ValueError("Stored chat message has an unknown source.")
        if source == "chatbot":
            source_name = _normalized_text(source_name, "chatbot source name", 100)
        elif source_name is not None:
            raise ValueError("Only chatbot messages may specify a source name.")
        return ChatMessage(
            turn_index=value["turn_index"],
            source=source,
            source_name=source_name,
            text=_normalized_text(value.get("text"), "message", 20_000),
            created_at=_normalized_text(value.get("created_at"), "created_at", 100),
        )

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    def _append(self, source: MessageSource, text: str, source_name: str | None = None) -> ChatMessage:
        normalized = _normalized_text(text, "message")
        if source == "chatbot":
            source_name = _normalized_text(source_name, "chatbot source name", 100)
        elif source_name is not None:
            raise ValueError("Only chatbot messages may specify a source name.")
        message = ChatMessage(
            turn_index=len(self._messages) + 1,
            source=source,
            source_name=source_name,
            text=normalized,
            created_at=_now(),
        )
        self._messages.append(message)
        self._persist()
        return message

    def add_user_message(self, text: str) -> ChatMessage:
        return self._append("user", text)

    def add_jarvis_message(self, text: str) -> ChatMessage:
        return self._append("jarvis", text)

    def ask_chatbot(self, chatbot_name: str, text: str) -> ChatMessage:
        normalized_name = _normalized_text(chatbot_name, "chatbot_name", 100)
        chatbot = self.chatbots.get(normalized_name)
        if chatbot is None:
            raise KeyError(f"No chatbot adapter is registered as {normalized_name!r}.")
        response = chatbot.send_message(_normalized_text(text, "chatbot prompt"))
        return self._append("chatbot", response, chatbot.name)

    def converse(
        self,
        user_text: str,
        *,
        chatbot_name: str | None = None,
        chatbot_prompt: str | None = None,
        jarvis_response: str | None = None,
    ) -> tuple[ChatMessage, ...]:
        """Record one user turn, optionally delegate, and record Jarvis's response."""
        added = [self.add_user_message(user_text)]
        if chatbot_name is not None:
            prompt = chatbot_prompt if chatbot_prompt is not None else user_text
            added.append(self.ask_chatbot(chatbot_name, prompt))
        if jarvis_response is not None:
            added.append(self.add_jarvis_message(jarvis_response))
        return tuple(added)

    def _key_points(self) -> list[str]:
        points: list[str] = []
        for message in self._messages:
            if message.source in {"user", "chatbot"}:
                prefix = "Utente" if message.source == "user" else f"{message.source_name}"
                points.append(f"{prefix}: {message.text[:500]}")
        return points[-40:]

    def _persist(self) -> None:
        payload = {
            "session_id": self.session_id,
            "messages": [asdict(message) for message in self._messages],
        }
        self.memory_store.remember(
            "session", self._session_memory_key(self.session_id), payload
        )
        key_points = self._key_points()
        self.memory_store.remember(
            "long_term", f"chat:{self.session_id}:key_points", key_points
        )
        checkpoint_id = self.memory_store.checkpoint(
            {
                "kind": "chat_session",
                "session_id": self.session_id,
                "message_count": len(self._messages),
                "last_turn_index": self._messages[-1].turn_index,
            }
        )
        self.memory_store.record_event(
            f"chat:{self.session_id}:turn:{self._messages[-1].turn_index}",
            "chat_message_recorded",
            {
                "source": self._messages[-1].source,
                "source_name": self._messages[-1].source_name,
                "checkpoint_id": checkpoint_id,
            },
        )

    def _planning_context(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "turn_index": item.turn_index,
                "source": item.source,
                "source_name": item.source_name,
                "text": item.text,
            }
            for item in self._messages[-30:]
        )

    def plan_content(
        self,
        topic: str,
        user_preferences: Mapping[str, Any] | None = None,
    ) -> ContentPlan:
        topic = _normalized_text(topic, "topic", limit=2000)
        if user_preferences is not None and not isinstance(user_preferences, Mapping):
            raise TypeError("user_preferences must be a mapping.")
        preferences = dict(user_preferences or {})
        try:
            json.dumps(preferences, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("user_preferences must be JSON serializable.") from exc
        if len(json.dumps(preferences, ensure_ascii=False).encode("utf-8")) > 50_000:
            raise ValueError("user_preferences must not exceed 50 KB.")

        context = self._planning_context()
        key_points = tuple(
            item
            for item in (
                self.memory_store.recall(
                    "long_term", f"chat:{self.session_id}:key_points"
                )
                or []
            )
            if isinstance(item, str)
        )
        suggestions: list[ChatbotSuggestion] = []
        request = json.dumps(
            {
                "task": "Propose a concise, factual content-plan suggestion.",
                "topic": topic,
                "user_preferences": preferences,
                "conversation_context": context,
                "long_term_key_points": key_points,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for chatbot_name, chatbot in self.chatbots.items():
            response = chatbot.send_message(request)
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError(f"Chatbot {chatbot_name} returned an empty suggestion.")
            suggestion = ChatbotSuggestion(chatbot_name, response.strip())
            suggestions.append(suggestion)
            self._append("chatbot", suggestion.text, chatbot_name)

        user_messages = [item for item in context if item["source"] == "user"]
        user_request = user_messages[-1]["text"] if user_messages else topic
        source_summary = (
            f"L'utente ha chiesto: {user_request}. "
            if user_request != topic
            else f"L'utente ha chiesto un piano su: {topic}. "
        )
        if suggestions:
            contributions = "; ".join(
                f"{item.chatbot_name} ha suggerito: {item.text}"
                for item in suggestions
            )
            synthesis = (
                source_summary
                + contributions
                + ". Jarvis combina questi contributi con le preferenze indicate "
                "in una scaletta verificabile, senza attribuire ai chatbot "
                "informazioni non presenti nelle loro risposte."
            )
        else:
            synthesis = (
                source_summary
                + "Jarvis struttura il piano usando solo il contesto disponibile; "
                "nessun chatbot esterno è configurato."
            )
        outline = self._outline(topic, preferences, suggestions)
        created_at = _now()
        identity = hashlib.sha256(
            json.dumps(
                [self.session_id, topic, preferences, context, [asdict(s) for s in suggestions]],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        plan = ContentPlan(
            plan_id=f"content_plan_{identity[:24]}",
            topic=topic,
            user_preferences=preferences,
            conversation_context=context,
            key_points=key_points,
            chatbot_suggestions=tuple(suggestions),
            jarvis_synthesis=synthesis,
            outline=outline,
            created_at=created_at,
        )
        self._append("jarvis", synthesis)
        self.memory_store.save_record(
            "chat_content_plans",
            plan.plan_id,
            {
                **asdict(plan),
                "conversation_context": list(plan.conversation_context),
                "key_points": list(plan.key_points),
                "chatbot_suggestions": [
                    asdict(item) for item in plan.chatbot_suggestions
                ],
                "outline": list(plan.outline),
            },
        )
        return plan

    @staticmethod
    def _outline(
        topic: str,
        preferences: Mapping[str, Any],
        suggestions: list[ChatbotSuggestion],
    ) -> tuple[str, ...]:
        sections = [
            f"Obiettivo e pubblico del contenuto su {topic}",
            "Contesto e punti chiave emersi dalla conversazione",
        ]
        if preferences:
            sections.append("Vincoli di formato, tono e preferenze dell'utente")
        if suggestions:
            sections.append("Sintesi dei contributi chatbot, mantenendo le fonti attribuite")
        sections.extend(
            (
                "Sviluppo dei contenuti con affermazioni verificabili",
                "Revisione finale, incertezze e prossimi passi",
            )
        )
        return tuple(sections)

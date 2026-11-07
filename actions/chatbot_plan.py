"""Expose the persistent ChatOrchestrator using an offline mock chatbot."""

from __future__ import annotations

import json
from typing import Any

from core.chat_orchestrator import ChatOrchestrator


def chatbot_plan(
    parameters: dict[str, Any] | None = None,
    *,
    chat_orchestrator: ChatOrchestrator | None = None,
    **_context: Any,
) -> str:
    values = parameters or {}
    topic = values.get("topic")
    preferences = values.get("user_preferences") or {}
    if not isinstance(topic, str) or not topic.strip():
        return "A non-empty content-planning topic is required."
    if not isinstance(preferences, dict):
        return "user_preferences must be an object."
    if chat_orchestrator is None:
        raise RuntimeError("The Jarvis ChatOrchestrator is unavailable.")
    chat_orchestrator.add_user_message(topic)
    plan = chat_orchestrator.plan_content(topic, preferences)
    return json.dumps(
        {
            "topic": plan.topic,
            "key_points": list(plan.key_points),
            "suggestions": [
                {"chatbot": item.chatbot_name, "text": item.text}
                for item in plan.chatbot_suggestions
            ],
            "jarvis_synthesis": plan.jarvis_synthesis,
            "outline": list(plan.outline),
            "plan_id": plan.plan_id,
        },
        ensure_ascii=False,
    )


TOOL = {
    "name": "chatbot_plan",
    "description": (
        "Create a persistent multi-turn content plan using ChatOrchestrator and "
        "the configured chatbot adapters. The default MockChatbot is offline and "
        "must be described as a mock, not as an external AI service."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {"type": "STRING"},
            "user_preferences": {"type": "OBJECT"},
        },
        "required": ["topic"],
    },
    "handler": chatbot_plan,
}

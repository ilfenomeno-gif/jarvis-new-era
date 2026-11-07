import json
import sqlite3

import pytest

from core.chat_orchestrator import ChatOrchestrator
from core.chatbot_bridge import MockChatbot
from core.memory_store import MemoryStore


def test_multi_turn_conversation_keeps_order_and_context(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    orchestrator = ChatOrchestrator(store, session_id="multi-turn")
    orchestrator.converse("Voglio scrivere un articolo sul riciclo.")
    orchestrator.converse(
        "Il pubblico sono studenti.",
        jarvis_response="Terrò presente il pubblico scolastico.",
    )

    assert [message.turn_index for message in orchestrator.messages] == [1, 2, 3]
    assert [message.source for message in orchestrator.messages] == [
        "user",
        "user",
        "jarvis",
    ]
    assert orchestrator.messages[0].text == "Voglio scrivere un articolo sul riciclo."
    assert orchestrator.messages[1].text == "Il pubblico sono studenti."
    assert orchestrator.messages[2].source_name is None


def test_sources_are_attributed_including_named_chatbot(tmp_path):
    chatbot = MockChatbot("ResearchBot", ["Usa esempi locali."])
    orchestrator = ChatOrchestrator(
        MemoryStore(tmp_path / "memory.sqlite3"),
        session_id="attribution",
        chatbots={"ResearchBot": chatbot},
    )

    messages = orchestrator.converse(
        "Crea una guida per studenti.",
        chatbot_name="ResearchBot",
        jarvis_response="Preparerò la guida con esempi adatti agli studenti.",
    )

    assert [(item.source, item.source_name) for item in messages] == [
        ("user", None),
        ("chatbot", "ResearchBot"),
        ("jarvis", None),
    ]


def test_session_and_long_term_key_points_persist_after_restart(tmp_path):
    database = tmp_path / "memory.sqlite3"
    store = MemoryStore(database)
    first = ChatOrchestrator(store, session_id="persisted")
    first.converse(
        "Pianifica una serie di video sulla botanica.",
        jarvis_response="La serie sarà divulgativa e pratica.",
    )
    restarted_store = MemoryStore(database)
    restarted = ChatOrchestrator(restarted_store, session_id="persisted")

    assert restarted.messages == first.messages
    assert restarted_store.recall(
        "long_term", "chat:persisted:key_points"
    ) == ["Utente: Pianifica una serie di video sulla botanica."]
    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            "SELECT state_json FROM jarvis_checkpoints"
        ).fetchall()
    checkpoints = [json.loads(row[0]) for row in rows]
    assert any(
        item["session_id"] == "persisted"
        and item["message_count"] == 2
        and item["kind"] == "chat_session"
        for item in checkpoints
    )


def test_content_plan_combines_user_chatbot_and_jarvis_attributions(tmp_path):
    chatbot = MockChatbot("EditorialBot", ["Inserisci un'introduzione con una domanda."])
    store = MemoryStore(tmp_path / "memory.sqlite3")
    orchestrator = ChatOrchestrator(
        store,
        session_id="planning",
        chatbots={"EditorialBot": chatbot},
    )
    orchestrator.converse(
        "Vorrei un articolo breve per principianti.",
        jarvis_response="Il tono sarà semplice e diretto.",
    )

    plan = orchestrator.plan_content(
        "coltivare erbe aromatiche",
        {"audience": "principianti", "tone": "semplice", "format": "articolo breve"},
    )

    assert plan.topic == "coltivare erbe aromatiche"
    assert plan.user_preferences["audience"] == "principianti"
    assert plan.chatbot_suggestions[0].chatbot_name == "EditorialBot"
    assert "L'utente ha chiesto: Vorrei un articolo breve per principianti." in (
        plan.jarvis_synthesis
    )
    assert "EditorialBot ha suggerito: Inserisci un'introduzione con una domanda." in (
        plan.jarvis_synthesis
    )
    assert orchestrator.messages[-1].source == "jarvis"
    assert orchestrator.messages[-1].text == plan.jarvis_synthesis
    persisted = store.load_record("chat_content_plans", plan.plan_id)
    assert persisted["topic"] == plan.topic
    assert persisted["chatbot_suggestions"][0]["chatbot_name"] == "EditorialBot"
    sent = json.loads(chatbot.sent_messages[0])
    assert sent["topic"] == plan.topic
    assert sent["long_term_key_points"]
    assert sent["conversation_context"][0]["source"] == "user"
    assert sent["conversation_context"][1]["source"] == "jarvis"


def test_planning_without_chatbot_is_explicit_about_missing_external_sources(tmp_path):
    orchestrator = ChatOrchestrator(
        MemoryStore(tmp_path / "memory.sqlite3"), session_id="offline-plan"
    )

    plan = orchestrator.plan_content("educazione ambientale")

    assert plan.chatbot_suggestions == ()
    assert "nessun chatbot esterno è configurato" in plan.jarvis_synthesis
    assert len(plan.outline) >= 3


def test_unknown_chatbot_invalid_messages_and_preferences_are_rejected(tmp_path):
    orchestrator = ChatOrchestrator(
        MemoryStore(tmp_path / "memory.sqlite3"), session_id="validation"
    )

    with pytest.raises(KeyError, match="registered"):
        orchestrator.ask_chatbot("MissingBot", "hello")
    with pytest.raises(ValueError, match="message"):
        orchestrator.add_user_message(" ")
    with pytest.raises(ValueError, match="JSON serializable"):
        orchestrator.plan_content("topic", {"bad": object()})


def test_chatbot_failure_is_not_recorded_as_a_successful_message(tmp_path):
    chatbot = MockChatbot("FailingBot", [])
    orchestrator = ChatOrchestrator(
        MemoryStore(tmp_path / "memory.sqlite3"),
        session_id="failure",
        chatbots={"FailingBot": chatbot},
    )
    orchestrator.add_user_message("Prepare a plan.")

    with pytest.raises(RuntimeError, match="no more responses"):
        orchestrator.ask_chatbot("FailingBot", "Suggest a plan.")

    assert [message.source for message in orchestrator.messages] == ["user"]

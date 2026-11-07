import pytest

from core.chatbot_bridge import BaseChatbot, MockChatbot


def test_mock_chatbot_sends_message_and_returns_configured_response():
    chatbot = MockChatbot("WriterBot", ["Outline idea", "Revision idea"])

    first = chatbot.send_message("Plan a short article.")
    second = chatbot.send_message("Revise the outline.")

    assert first == "Outline idea"
    assert second == "Revision idea"
    assert chatbot.name == "WriterBot"
    assert chatbot.sent_messages == [
        "Plan a short article.",
        "Revise the outline.",
    ]


def test_mock_chatbot_supports_callable_responder():
    chatbot = MockChatbot("EchoBot", lambda text: f"Received: {text}")

    assert chatbot.send_message("hello") == "Received: hello"


def test_base_chatbot_is_an_adapter_contract():
    class LocalAdapter(BaseChatbot):
        def send_message(self, text: str) -> str:
            return text.upper()

    assert LocalAdapter("Local").send_message("hello") == "HELLO"
    with pytest.raises(TypeError):
        BaseChatbot("incomplete")


@pytest.mark.parametrize("text", ["", "  \n"])
def test_mock_chatbot_rejects_empty_requests(text):
    with pytest.raises(ValueError, match="non-empty"):
        MockChatbot().send_message(text)


def test_mock_chatbot_reports_exhausted_responses():
    chatbot = MockChatbot("FiniteBot", ["one"])
    assert chatbot.send_message("first") == "one"
    with pytest.raises(RuntimeError, match="no more responses"):
        chatbot.send_message("second")


def test_mock_chatbot_rejects_invalid_name_and_response():
    with pytest.raises(ValueError, match="Chatbot name"):
        MockChatbot(" ")
    with pytest.raises(TypeError, match="responses"):
        MockChatbot("Bot", [1])

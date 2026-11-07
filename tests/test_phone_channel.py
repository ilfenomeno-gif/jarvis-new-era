import pytest

from core.phone_channel import (
    MockPhoneChannel,
    PhoneChannelError,
    PhoneMessage,
    TelegramAdapter,
)


class FakeSecretStore:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def get(self, key):
        assert key == TelegramAdapter.SECRET_KEY
        if self.error:
            raise self.error
        return self.value


def test_mock_channel_sends_and_polls_messages():
    channel = MockPhoneChannel()
    channel.enqueue_incoming("Jarvis, come stai?", chat_id="chat-hidden", sender_id="user-hidden")

    received = channel.poll_messages()
    channel.send_message("Sto bene.")

    assert received == [
        PhoneMessage("Jarvis, come stai?", "chat-hidden", "user-hidden", 1)
    ]
    assert channel.sent_messages == ["Sto bene."]
    assert channel.poll_messages() == []
    assert "chat-hidden" not in repr(received[0])


def test_telegram_adapter_parses_secret_store_token_and_sends_with_mock_transport():
    calls = []

    def transport(url, payload, timeout):
        calls.append((url, dict(payload), timeout))
        return {"ok": True, "result": {"message_id": 7}}

    adapter = TelegramAdapter(
        FakeSecretStore("12345:mock-token"),
        "private-chat-id",
        enabled=True,
        transport=transport,
    )

    adapter.send_message("Task completed")

    assert calls == [
        (
            "https://api.telegram.org/bot12345:mock-token/sendMessage",
            {"chat_id": "private-chat-id", "text": "Task completed"},
            10.0,
        )
    ]
    assert "mock-token" not in repr(adapter)
    assert "private-chat-id" not in repr(adapter)


def test_telegram_poll_parses_messages_and_advances_offset_with_mock():
    requests = []

    def transport(url, payload, _timeout):
        requests.append((url.rsplit("/", 1)[-1], dict(payload)))
        return {
            "ok": True,
            "result": [
                {
                    "update_id": 41,
                    "message": {
                        "message_id": 9,
                        "text": "/status",
                        "chat": {"id": 1001},
                        "from": {"id": 2002},
                    },
                },
                {"update_id": 42, "message": {"text": "non-message"}},
            ],
        }

    adapter = TelegramAdapter(
        FakeSecretStore("bot-secret"),
        "recipient-secret",
        enabled=True,
        transport=transport,
    )

    messages = adapter.poll_messages()
    adapter.poll_messages()

    assert messages == [PhoneMessage("/status", "1001", "2002", 9)]
    assert requests[0][0] == requests[1][0] == "getUpdates"
    assert requests[1][1]["offset"] == 43
    assert "bot-secret" not in repr(adapter)
    assert "recipient-secret" not in repr(adapter)


def test_telegram_adapter_fails_closed_when_disabled_or_token_missing():
    calls = []
    disabled = TelegramAdapter(
        FakeSecretStore("token"),
        "chat-id",
        transport=lambda *args: calls.append(args) or {"ok": True, "result": []},
    )
    with pytest.raises(PhoneChannelError, match="disabled"):
        disabled.send_message("No message")

    enabled_without_token = TelegramAdapter(
        FakeSecretStore(),
        "chat-id",
        enabled=True,
        transport=lambda *args: calls.append(args) or {"ok": True, "result": []},
    )
    with pytest.raises(PhoneChannelError, match="missing from SecretStore"):
        enabled_without_token.poll_messages()
    assert calls == []


def test_telegram_transport_errors_do_not_leak_token_or_chat_id():
    token = "sensitive-bot-token"
    chat_id = "sensitive-chat-id"

    def failing_transport(*_args):
        raise RuntimeError(f"failed URL contained {token} and {chat_id}")

    adapter = TelegramAdapter(
        FakeSecretStore(token),
        chat_id,
        enabled=True,
        transport=failing_transport,
    )
    with pytest.raises(PhoneChannelError) as error:
        adapter.send_message("hello")
    assert token not in str(error.value)
    assert chat_id not in str(error.value)


def test_mock_channel_reports_unconfigured_state():
    channel = MockPhoneChannel()
    channel.configured = False

    with pytest.raises(PhoneChannelError, match="not configured"):
        channel.send_message("notification")
    with pytest.raises(PhoneChannelError, match="not configured"):
        channel.poll_messages()

import pytest

from core.message_router import MessageRouter
from core.phone_channel import MockPhoneChannel, PhoneChannelError


def _router(channel, calls, *, allowed_sender_ids=None):
    return MessageRouter(
        channel,
        jarvis_handler=lambda message: calls.append(("jarvis", message.text)) or "Jarvis reply",
        status_handler=lambda message: calls.append(("status", message.text)) or "System status",
        stop_handler=lambda message: calls.append(("stop", message.text)) or "Stop requested",
        override_handler=lambda message: calls.append(("override", message.text))
        or "Override forwarded for security review",
        allowed_sender_ids=(
            allowed_sender_ids if allowed_sender_ids is not None else {"mock-sender"}
        ),
    )


def test_incoming_phone_message_is_forwarded_to_jarvis_and_replied():
    channel = MockPhoneChannel()
    calls = []
    channel.enqueue_incoming("Jarvis, come stai?")
    router = _router(channel, calls)

    responses = router.poll_once()

    assert calls == [("jarvis", "Jarvis, come stai?")]
    assert responses[0][1] == "Jarvis reply"
    assert channel.sent_messages == ["Jarvis reply"]


def test_jarvis_notification_is_routed_to_phone_channel():
    channel = MockPhoneChannel()
    calls = []
    router = _router(channel, calls)

    router.send_notification("Task completato")

    assert channel.sent_messages == ["Task completato"]
    assert calls == []


def test_status_command_uses_status_handler():
    channel = MockPhoneChannel()
    calls = []
    channel.enqueue_incoming("/status")

    responses = _router(channel, calls).poll_once()

    assert calls == [("status", "/status")]
    assert responses[0][1] == "System status"
    assert channel.sent_messages == ["System status"]


def test_stop_and_override_are_forwarded_to_the_security_hooks():
    channel = MockPhoneChannel()
    calls = []
    channel.enqueue_incoming("/stop")
    channel.enqueue_incoming("AUTORIZZO OVERRIDE per il task corrente")

    responses = _router(channel, calls).poll_once()

    assert [kind for kind, _ in calls] == ["stop", "override"]
    assert responses[1][1] == "Override forwarded for security review"
    assert channel.sent_messages == [
        "Stop requested",
        "Override forwarded for security review",
    ]


def test_unauthorized_sender_is_ignored_without_reply():
    channel = MockPhoneChannel()
    calls = []
    channel.enqueue_incoming(
        "Jarvis, run a task", chat_id="hidden-chat", sender_id="unauthorized"
    )

    responses = _router(
        channel, calls, allowed_sender_ids={"authorized"}
    ).poll_once()

    assert responses == []
    assert calls == []
    assert channel.sent_messages == []


def test_router_propagates_unconfigured_channel_error():
    channel = MockPhoneChannel()
    channel.configured = False
    router = _router(channel, [])

    with pytest.raises(PhoneChannelError, match="not configured"):
        router.send_notification("Task completed")


def test_router_rejects_all_incoming_messages_without_sender_allowlist():
    channel = MockPhoneChannel()
    calls = []
    channel.enqueue_incoming("Jarvis, execute this.")
    router = MessageRouter(
        channel,
        jarvis_handler=lambda message: calls.append(message) or "reply",
        status_handler=lambda _message: "status",
        stop_handler=lambda _message: "stop",
        override_handler=lambda _message: "review",
    )

    assert router.poll_once() == []
    assert calls == []
    assert channel.sent_messages == []

"""Phone messaging interfaces with an opt-in Telegram Bot API adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


class PhoneChannelError(RuntimeError):
    """A phone-channel operation failed without exposing credentials."""


@dataclass(frozen=True)
class PhoneMessage:
    text: str
    chat_id: str = field(repr=False)
    sender_id: str = field(repr=False)
    message_id: int = 0


class BasePhoneChannel(ABC):
    @abstractmethod
    def send_message(self, text: str) -> None:
        """Send a text message through the configured phone channel."""

    @abstractmethod
    def poll_messages(self) -> list[PhoneMessage]:
        """Return newly received, normalized text messages."""


class MockPhoneChannel(BasePhoneChannel):
    """In-memory bidirectional channel for tests; makes no network requests."""

    def __init__(self) -> None:
        self.sent_messages: list[str] = []
        self._incoming: list[PhoneMessage] = []
        self.configured = True

    def enqueue_incoming(
        self,
        text: str,
        *,
        chat_id: str = "mock-chat",
        sender_id: str = "mock-sender",
    ) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Phone message must be non-empty text.")
        self._incoming.append(
            PhoneMessage(text.strip(), str(chat_id), str(sender_id), len(self._incoming) + 1)
        )

    def send_message(self, text: str) -> None:
        if not self.configured:
            raise PhoneChannelError("Phone channel is not configured.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Phone message must be non-empty text.")
        self.sent_messages.append(text.strip())

    def poll_messages(self) -> list[PhoneMessage]:
        if not self.configured:
            raise PhoneChannelError("Phone channel is not configured.")
        messages, self._incoming = self._incoming, []
        return messages


Transport = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]


def _telegram_http_transport(
    url: str, payload: Mapping[str, Any], timeout: float
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Invalid Telegram response.")
    return decoded


class TelegramAdapter(BasePhoneChannel):
    """Telegram Bot API transport, disabled unless explicitly enabled.

    Store the bot token in SecretStore under ``phone:telegram:bot_token``.
    No token or chat identifier is included in exceptions, reprs or logs.
    """

    SECRET_KEY = "phone:telegram:bot_token"

    def __init__(
        self,
        secret_store,
        chat_id: str,
        *,
        enabled: bool = False,
        transport: Transport | None = None,
        timeout: float = 10,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be an explicit boolean.")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            raise ValueError("timeout must be greater than 0 and at most 60 seconds.")
        normalized_chat_id = str(chat_id).strip() if chat_id is not None else ""
        if not normalized_chat_id or len(normalized_chat_id) > 200:
            raise ValueError("A valid Telegram chat ID is required.")
        self._secret_store = secret_store
        self._chat_id = normalized_chat_id
        self.enabled = enabled
        self._transport = transport or _telegram_http_transport
        self.timeout = float(timeout)
        self._offset: int | None = None

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self._load_token())

    def _load_token(self) -> str:
        try:
            token = self._secret_store.get(self.SECRET_KEY)
        except Exception:
            raise PhoneChannelError(
                "Telegram bot token could not be loaded from secure storage."
            ) from None
        if not isinstance(token, str) or not token.strip():
            raise PhoneChannelError(
                "Telegram bot token is missing from SecretStore."
            )
        return token.strip()

    def _api_call(self, method: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not self.enabled:
            raise PhoneChannelError(
                "Telegram adapter is disabled; enable it explicitly before use."
            )
        token = self._load_token()
        url = f"https://api.telegram.org/bot{token}/{method}"
        try:
            result = self._transport(url, payload, self.timeout)
        except Exception:
            raise PhoneChannelError(
                f"Telegram {method} request failed; sensitive details were omitted."
            ) from None
        if not isinstance(result, Mapping) or result.get("ok") is not True:
            raise PhoneChannelError(
                f"Telegram {method} returned an unsuccessful response."
            )
        return result

    def send_message(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Phone message must be non-empty text.")
        self._api_call(
            "sendMessage",
            {"chat_id": self._chat_id, "text": text.strip()},
        )

    def poll_messages(self) -> list[PhoneMessage]:
        payload: dict[str, Any] = {"timeout": 0, "allowed_updates": ["message"]}
        if self._offset is not None:
            payload["offset"] = self._offset
        response = self._api_call("getUpdates", payload)
        updates = response.get("result")
        if not isinstance(updates, list):
            raise PhoneChannelError("Telegram getUpdates returned an invalid response.")
        messages: list[PhoneMessage] = []
        for update in updates:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int) and not isinstance(update_id, bool):
                self._offset = max(self._offset or 0, update_id + 1)
            message = update.get("message")
            if not isinstance(message, dict):
                continue
            text = message.get("text")
            chat = message.get("chat")
            sender = message.get("from")
            if (
                not isinstance(text, str)
                or not text.strip()
                or not isinstance(chat, dict)
                or not isinstance(sender, dict)
                or chat.get("id") is None
                or sender.get("id") is None
            ):
                continue
            message_id = message.get("message_id", 0)
            messages.append(
                PhoneMessage(
                    text=text.strip(),
                    chat_id=str(chat["id"]),
                    sender_id=str(sender["id"]),
                    message_id=(
                        message_id
                        if isinstance(message_id, int) and not isinstance(message_id, bool)
                        else 0
                    ),
                )
            )
        return messages

"""Route phone messages to Jarvis callbacks and notifications back to a channel."""

from __future__ import annotations

import logging
import re
from typing import Callable, Iterable

from core.phone_channel import BasePhoneChannel, PhoneChannelError, PhoneMessage

MessageHandler = Callable[[str], str]
CommandHandler = Callable[[PhoneMessage], str]


class MessageRouter:
    def __init__(
        self,
        channel: BasePhoneChannel,
        *,
        jarvis_handler: MessageHandler,
        status_handler: CommandHandler,
        stop_handler: CommandHandler,
        override_handler: CommandHandler | None = None,
        terminal_agent=None,
        allowed_sender_ids: Iterable[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not isinstance(channel, BasePhoneChannel):
            raise TypeError("channel must implement BasePhoneChannel.")
        self.channel = channel
        self.jarvis_handler = jarvis_handler
        self.status_handler = status_handler
        self.stop_handler = stop_handler
        if terminal_agent is not None:
            phone_override = getattr(terminal_agent, "handle_phone_override", None)
            if not callable(phone_override):
                raise TypeError("terminal_agent must provide handle_phone_override().")
            self.override_handler = phone_override
        elif override_handler is not None:
            self.override_handler = override_handler
        else:
            raise TypeError("override_handler or terminal_agent must be configured.")
        self.allowed_sender_ids = frozenset(
            str(item) for item in (allowed_sender_ids or ())
        )
        self.logger = logger or logging.getLogger(__name__)

    def send_notification(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Notification text must be non-empty.")
        try:
            self.channel.send_message(text.strip())
        except PhoneChannelError:
            self.logger.warning("Phone notification could not be delivered.")
            raise

    @staticmethod
    def _route_kind(text: str) -> str:
        normalized = text.strip()
        if re.fullmatch(r"/status(?:@\w+)?(?:\s+.*)?", normalized, re.IGNORECASE):
            return "status"
        if re.fullmatch(r"/stop(?:@\w+)?(?:\s+.*)?", normalized, re.IGNORECASE):
            return "stop"
        if re.search(r"\bAUTORIZZO\s+OVERRIDE\b", normalized, re.IGNORECASE):
            return "override"
        return "jarvis"

    def poll_once(self) -> list[tuple[PhoneMessage, str]]:
        responses: list[tuple[PhoneMessage, str]] = []
        for message in self.channel.poll_messages():
            if not self.allowed_sender_ids or message.sender_id not in self.allowed_sender_ids:
                self.logger.warning("Rejected phone message from an unauthorized sender.")
                continue
            route_kind = self._route_kind(message.text)
            handler = {
                "status": self.status_handler,
                "stop": self.stop_handler,
                "override": self.override_handler,
                "jarvis": self.jarvis_handler,
            }[route_kind]
            response = handler(message)
            if not isinstance(response, str) or not response.strip():
                response = "Comando ricevuto."
            response = response.strip()
            self.send_notification(response)
            responses.append((message, response))
        return responses

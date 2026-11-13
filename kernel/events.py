"""Small asynchronous event bus owned by one application event loop."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import uuid4

EventHandler = Callable[["Event"], Awaitable[None]]


class EventBusClosedError(RuntimeError):
    """Raised when an operation is attempted after the bus is closed."""


class EventDispatchError(RuntimeError):
    """Aggregates subscriber failures after all current subscribers were called."""

    def __init__(self, event_name: str, errors: tuple[Exception, ...]) -> None:
        self.event_name = event_name
        self.errors = errors
        super().__init__(
            f"{len(errors)} subscriber(s) failed while handling {event_name!r}."
        )


@dataclass(frozen=True, slots=True)
class Event:
    """Immutable event envelope with a stable name and optional correlation ID."""

    name: str
    payload: Mapping[str, object] = field(default_factory=dict)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Event name must not be empty.")
        if not isinstance(self.payload, Mapping):
            raise TypeError("Event payload must be a mapping.")
        if not all(isinstance(key, str) for key in self.payload):
            raise TypeError("Event payload keys must be strings.")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class Subscription:
    event_name: str
    token: str


class EventBus:
    """In-process async pub/sub with explicit subscription and error handling."""

    def __init__(self) -> None:
        self._handlers: dict[str, dict[str, EventHandler]] = {}
        self._closed = False

    def subscribe(self, event_name: str, handler: EventHandler) -> Subscription:
        self._ensure_open()
        if not isinstance(event_name, str) or not event_name.strip():
            raise ValueError("Event name must not be empty.")
        if not callable(handler):
            raise TypeError("Event handlers must be async callables.")
        is_async_callable = inspect.iscoroutinefunction(
            handler
        ) or inspect.iscoroutinefunction(handler.__call__)
        if not is_async_callable:
            raise TypeError("Event handlers must be async callables.")
        name = event_name.strip()
        token = uuid4().hex
        self._handlers.setdefault(name, {})[token] = handler
        return Subscription(event_name=name, token=token)

    def unsubscribe(self, subscription: Subscription) -> bool:
        if not isinstance(subscription, Subscription):
            raise TypeError("subscription must be a Subscription.")
        handlers = self._handlers.get(subscription.event_name)
        if handlers is None or subscription.token not in handlers:
            return False
        del handlers[subscription.token]
        if not handlers:
            del self._handlers[subscription.event_name]
        return True

    async def publish(self, event: Event) -> None:
        self._ensure_open()
        if not isinstance(event, Event):
            raise TypeError("event must be an Event.")
        errors: list[Exception] = []
        for handler in tuple(self._handlers.get(event.name, {}).values()):
            try:
                await handler(event)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise EventDispatchError(event.name, tuple(errors))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._handlers.clear()

    def _ensure_open(self) -> None:
        if self._closed:
            raise EventBusClosedError("The event bus is closed.")

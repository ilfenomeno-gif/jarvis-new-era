"""Provider-neutral social publishing interfaces with safe mock adapters.

Live adapters must be backed by the platform's official, authorized API client;
browser automation, scraping, and unauthorized bots are intentionally absent.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from core.account_manager import AccountCredentials


@dataclass(frozen=True)
class PublishResult:
    platform: str
    publication_id: str
    status: str


class BasePublisher(ABC):
    platform: str

    @abstractmethod
    def publish(self, content: str, media_path: str | Path | None = None) -> PublishResult:
        """Publish through an authorized platform interface."""


class OfficialSocialApiClient(Protocol):
    def publish(
        self,
        platform: str,
        content: str,
        media_path: str | Path | None,
        credentials: AccountCredentials,
    ) -> PublishResult: ...


class MockPublisher(BasePublisher):
    def __init__(
        self,
        platform: str = "mock",
        responder: Callable[[str, str | Path | None], PublishResult] | None = None,
    ) -> None:
        normalized = platform.strip().casefold() if isinstance(platform, str) else ""
        if not normalized:
            raise ValueError("Publisher platform must not be empty.")
        self.platform = normalized
        self.responder = responder
        self.calls: list[tuple[str, str | Path | None]] = []

    def publish(
        self, content: str, media_path: str | Path | None = None
    ) -> PublishResult:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Post content must be non-empty text.")
        self.calls.append((content, media_path))
        if self.responder is not None:
            result = self.responder(content, media_path)
        else:
            result = PublishResult(
                self.platform, f"mock-{len(self.calls)}", "published"
            )
        if not isinstance(result, PublishResult):
            raise TypeError("Publisher responder must return PublishResult.")
        return result


class OfficialApiPublisher(BasePublisher):
    """Base for future platform API adapters; never simulates a live API."""

    def __init__(
        self,
        platform: str,
        client: OfficialSocialApiClient | None,
        credentials_provider: Callable[[str], AccountCredentials | None],
    ) -> None:
        self.platform = platform
        self._client = client
        self._credentials_provider = credentials_provider

    def publish(
        self, content: str, media_path: str | Path | None = None
    ) -> PublishResult:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Post content must be non-empty text.")
        if self._client is None:
            raise RuntimeError(
                f"{self.platform} official API client is not configured; "
                "no content was published."
            )
        credentials = self._credentials_provider(self.platform)
        if credentials is None:
            raise RuntimeError(
                f"No authorized {self.platform} account is configured; "
                "no content was published."
            )
        result = self._client.publish(
            self.platform, content.strip(), media_path, credentials
        )
        if not isinstance(result, PublishResult) or result.platform != self.platform:
            raise RuntimeError(
                f"{self.platform} official API client returned an invalid result."
            )
        return result


class InstagramPublisher(OfficialApiPublisher):
    def __init__(
        self,
        client: OfficialSocialApiClient | None = None,
        credentials_provider: Callable[[str], AccountCredentials | None] = lambda _platform: None,
    ) -> None:
        super().__init__("instagram", client, credentials_provider)


class TikTokPublisher(OfficialApiPublisher):
    def __init__(
        self,
        client: OfficialSocialApiClient | None = None,
        credentials_provider: Callable[[str], AccountCredentials | None] = lambda _platform: None,
    ) -> None:
        super().__init__("tiktok", client, credentials_provider)

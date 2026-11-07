from pathlib import Path

import pytest

from core.account_manager import AccountCredentials
from core.social_publishers import (
    BasePublisher,
    InstagramPublisher,
    MockPublisher,
    PublishResult,
    TikTokPublisher,
)


def test_mock_publisher_receives_content_and_media_path():
    publisher = MockPublisher("instagram")
    media_path = Path("photo.jpg")

    result = publisher.publish("A caption", media_path)

    assert publisher.calls == [("A caption", media_path)]
    assert result == PublishResult("instagram", "mock-1", "published")


def test_publisher_interface_is_extensible():
    class LocalPublisher(BasePublisher):
        platform = "instagram"

        def publish(self, content, media_path=None):
            return PublishResult(self.platform, content, "published")

    assert LocalPublisher().publish("ready").publication_id == "ready"


@pytest.mark.parametrize(
    ("publisher_type", "platform"),
    [(InstagramPublisher, "instagram"), (TikTokPublisher, "tiktok")],
)
def test_official_platform_adapter_delegates_to_injected_official_client(
    publisher_type, platform
):
    calls = []

    class OfficialClient:
        def publish(self, requested_platform, content, media_path, credentials):
            calls.append((requested_platform, content, media_path, credentials.username))
            return PublishResult(requested_platform, "official-42", "published")

    credentials = AccountCredentials(platform, "creator", "secret-token")
    publisher = publisher_type(
        OfficialClient(),
        credentials_provider=lambda _platform: credentials,
    )
    result = publisher.publish("Post text", "media.png")

    assert result.publication_id == "official-42"
    assert calls == [(platform, "Post text", "media.png", "creator")]


def test_official_platform_adapter_fails_closed_without_api_client():
    with pytest.raises(RuntimeError, match="not configured"):
        InstagramPublisher().publish("No live publish")


def test_official_platform_adapter_fails_closed_without_credentials():
    publisher = TikTokPublisher(
        object(), credentials_provider=lambda _platform: None
    )

    with pytest.raises(RuntimeError, match="No authorized"):
        publisher.publish("No live publish")


def test_mock_publisher_rejects_empty_content():
    with pytest.raises(ValueError, match="non-empty"):
        MockPublisher().publish(" ")

"""Explicit-confirmation social post preparation and publishing orchestration."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping

from core.internal_workflow import default_database_path
from core.social_publishers import BasePublisher, PublishResult

SUPPORTED_PLATFORMS = frozenset({"instagram", "tiktok"})


class SocialPublishError(RuntimeError):
    """Social publication could not be completed safely."""


@dataclass(frozen=True)
class SocialDraft:
    draft_id: str
    platform: str
    text: str
    image_path: str | None
    created_at: str


class SocialAgent:
    def __init__(
        self,
        publishers: Mapping[str, BasePublisher],
        *,
        database_path: str | Path | None = None,
        confirm: Callable[[str], bool] | None = None,
        autopilot: bool = False,
        logger: Callable[[str], object] | None = None,
    ) -> None:
        if not isinstance(autopilot, bool):
            raise TypeError("autopilot must be explicitly configured as a boolean.")
        if not publishers:
            raise ValueError("At least one social publisher must be configured.")
        self.publishers: dict[str, BasePublisher] = {}
        for platform, publisher in publishers.items():
            normalized = self._platform(platform)
            if not isinstance(publisher, BasePublisher):
                raise TypeError("Social publishers must implement BasePublisher.")
            if normalized != publisher.platform.casefold():
                raise ValueError("Publisher mapping key must match publisher.platform.")
            if normalized not in SUPPORTED_PLATFORMS:
                raise ValueError(f"Unsupported social platform: {normalized}.")
            self.publishers[normalized] = publisher
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self.confirm = confirm
        self.autopilot = autopilot
        self._logger = logger or (lambda _message: None)
        self._initialize()

    @staticmethod
    def _platform(platform: str) -> str:
        value = platform.strip().casefold() if isinstance(platform, str) else ""
        if value not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported social platform: {platform!r}.")
        return value

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS social_publications (
                    draft_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    text TEXT NOT NULL,
                    image_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    publication_id TEXT NOT NULL DEFAULT '',
                    error_type TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def prepare_post(
        self,
        platform: str,
        text: str,
        image_path: str | Path | None = None,
    ) -> SocialDraft:
        platform = self._platform(platform)
        if platform not in self.publishers:
            raise ValueError(f"No publisher is configured for {platform}.")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Post text must be non-empty.")
        normalized_text = text.strip()
        if len(normalized_text) > 10_000:
            raise ValueError("Post text must not exceed 10,000 characters.")
        normalized_image: str | None = None
        if image_path is not None:
            path = Path(image_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Post media file does not exist: {path}")
            normalized_image = str(path)
        draft = SocialDraft(
            draft_id=uuid.uuid4().hex,
            platform=platform,
            text=normalized_text,
            image_path=normalized_image,
            created_at=datetime.now(UTC).isoformat(timespec="milliseconds"),
        )
        self._save(draft, "draft")
        self._logger(f"Prepared {platform} social draft {draft.draft_id}.")
        return draft

    def publish(self, platform: str, draft: SocialDraft) -> PublishResult | None:
        platform = self._platform(platform)
        if not isinstance(draft, SocialDraft):
            raise TypeError("publish requires a SocialDraft.")
        if draft.platform != platform:
            raise ValueError("Draft platform does not match the requested platform.")
        publisher = self.publishers.get(platform)
        if publisher is None:
            raise ValueError(f"No publisher is configured for {platform}.")
        if not self.autopilot and self.confirm is None:
            raise SocialPublishError(
                "Explicit user confirmation is required; no content was published."
            )

        if not self._claim_draft(draft, "confirming" if not self.autopilot else "publishing"):
            raise SocialPublishError(
                "Draft is missing or already attempted; refusing duplicate publication."
            )
        if not self.autopilot:
            summary = (
                f"Publish draft {draft.draft_id} to {platform}? "
                f"Text length={len(draft.text)}; media={'yes' if draft.image_path else 'no'}."
            )
            try:
                confirmed = self.confirm(summary)
            except Exception as exc:
                self._transition(
                    draft.draft_id, "confirming", "cancelled",
                    error_type=type(exc).__name__,
                )
                raise SocialPublishError(
                    "Confirmation failed; no content was published."
                ) from None
            if confirmed is not True:
                self._transition(draft.draft_id, "confirming", "cancelled")
                self._logger(f"Cancelled {platform} social draft {draft.draft_id}.")
                return None
            if not self._transition(draft.draft_id, "confirming", "publishing"):
                raise SocialPublishError(
                    "Draft state changed during confirmation; no content was published."
                )

        try:
            result = publisher.publish(draft.text, draft.image_path)
        except Exception as exc:
            self._transition(
                draft.draft_id, "publishing", "failed", error_type=type(exc).__name__
            )
            self._logger(
                f"Failed {platform} social draft {draft.draft_id}: {type(exc).__name__}."
            )
            raise SocialPublishError(
                f"{platform} publication failed ({type(exc).__name__}); "
                "sensitive details were not logged."
            ) from None
        if (
            not isinstance(result, PublishResult)
            or result.platform != platform
            or result.status != "published"
            or not isinstance(result.publication_id, str)
            or not result.publication_id.strip()
            or len(result.publication_id) > 500
        ):
            self._transition(
                draft.draft_id,
                "publishing",
                "failed",
                error_type="InvalidPublisherResult",
            )
            raise SocialPublishError("Publisher returned an invalid publication result.")
        if not self._transition(
            draft.draft_id,
            "publishing",
            "published",
            publication_id=result.publication_id,
        ):
            raise SocialPublishError(
                "Publication completed but its state could not be committed."
            )
        self._logger(
            f"Published {platform} social draft {draft.draft_id}."
        )
        return result

    def _save(
        self,
        draft: SocialDraft,
        status: str,
        *,
        publication_id: str = "",
        error_type: str = "",
    ) -> None:
        if len(draft.text.encode("utf-8")) > 50_000:
            raise ValueError("Draft text exceeds the internal persistence size limit.")
        now = datetime.now(UTC).isoformat(timespec="milliseconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO social_publications (
                    draft_id, platform, text, image_path, status,
                    publication_id, error_type, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    status = excluded.status,
                    publication_id = excluded.publication_id,
                    error_type = excluded.error_type,
                    updated_at = excluded.updated_at
                """,
                (
                    draft.draft_id,
                    draft.platform,
                    draft.text,
                    draft.image_path or "",
                    status,
                    publication_id,
                    error_type,
                    draft.created_at,
                    now,
                ),
            )

    def _claim_draft(self, draft: SocialDraft, new_status: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE social_publications SET status = ?, updated_at = ?
                WHERE draft_id = ? AND platform = ? AND text = ?
                    AND image_path = ? AND status = 'draft'
                """,
                (
                    new_status,
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    draft.draft_id,
                    draft.platform,
                    draft.text,
                    draft.image_path or "",
                ),
            )
        return cursor.rowcount == 1

    def _transition(
        self,
        draft_id: str,
        expected_status: str,
        new_status: str,
        *,
        publication_id: str = "",
        error_type: str = "",
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE social_publications SET status = ?, publication_id = ?,
                    error_type = ?, updated_at = ?
                WHERE draft_id = ? AND status = ?
                """,
                (
                    new_status,
                    publication_id,
                    error_type,
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    draft_id,
                    expected_status,
                ),
            )
        return cursor.rowcount == 1

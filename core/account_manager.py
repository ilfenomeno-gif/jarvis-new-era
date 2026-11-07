"""Secure social account metadata and credential lookup."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.internal_workflow import default_database_path
from core.secret_store import SecretBackendError, SecretStore

SUPPORTED_PLATFORMS = frozenset({"instagram", "tiktok"})
_PLATFORM_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


@dataclass(frozen=True)
class AccountCredentials:
    platform: str
    username: str
    token: str = field(repr=False)


class AccountManager:
    """Keep tokens in SecretStore and non-secret account names in internal SQLite."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        secret_store=None,
        config_dir: str | Path | None = None,
        environ=None,
        logger: Callable[[str], object] | None = None,
    ) -> None:
        self.database_path = (
            Path(database_path) if database_path is not None else default_database_path()
        )
        self._environ = os.environ if environ is None else environ
        self._logger = logger or (lambda _message: None)
        if secret_store is None:
            config_root = Path(config_dir) if config_dir is not None else (
                Path(__file__).resolve().parents[1] / "config"
            )
            try:
                secret_store = SecretStore(config_root / "secrets.json")
            except SecretBackendError:
                secret_store = None
        self._secret_store = secret_store
        self._initialize()

    @staticmethod
    def _platform(platform: str) -> str:
        value = platform.strip().casefold() if isinstance(platform, str) else ""
        if value not in SUPPORTED_PLATFORMS:
            raise ValueError(f"Unsupported social platform: {platform!r}.")
        return value

    @staticmethod
    def _secret_key(platform: str) -> str:
        return f"social:{platform}:token"

    @staticmethod
    def _env_prefix(platform: str) -> str:
        return f"SOCIAL_{platform.upper()}_"

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS social_accounts (
                    platform TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def set_account(self, platform: str, username: str, token: str) -> None:
        platform = self._platform(platform)
        username = username.strip() if isinstance(username, str) else ""
        token = token.strip() if isinstance(token, str) else ""
        if not username or len(username) > 200:
            raise ValueError("Account username must contain 1 to 200 characters.")
        if not token:
            raise ValueError("Account token must not be empty.")
        if self._secret_store is None:
            raise RuntimeError(
                "Secure token storage is unavailable; configure account credentials "
                "through environment variables instead."
            )
        self._secret_store.set(self._secret_key(platform), token)
        if self._secret_store.get(self._secret_key(platform)) != token:
            raise RuntimeError(
                f"Secure storage verification failed for {platform}; credential was not saved."
            )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO social_accounts (platform, username, updated_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(platform) DO UPDATE SET
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (platform, username),
            )
        self._logger(f"Saved credentials for {platform} account {username}; token redacted.")

    def get_account(self, platform: str) -> AccountCredentials | None:
        platform = self._platform(platform)
        prefix = self._env_prefix(platform)
        env_username = str(self._environ.get(prefix + "USERNAME", "")).strip()
        env_token = str(self._environ.get(prefix + "TOKEN", "")).strip()
        if env_username or env_token:
            if not env_username or not env_token:
                raise ValueError(
                    f"Both {prefix}USERNAME and {prefix}TOKEN must be configured."
                )
            return AccountCredentials(platform, env_username, env_token)

        with self._connect() as connection:
            row = connection.execute(
                "SELECT username FROM social_accounts WHERE platform = ?",
                (platform,),
            ).fetchone()
        if row is None:
            return None
        if self._secret_store is None:
            return None
        token = self._secret_store.get(self._secret_key(platform))
        if not token:
            return None
        return AccountCredentials(platform, row[0], token)

    def remove_account(self, platform: str) -> bool:
        platform = self._platform(platform)
        deleted_secret = (
            self._secret_store.delete(self._secret_key(platform))
            if self._secret_store is not None
            else False
        )
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM social_accounts WHERE platform = ?", (platform,)
            )
        removed = deleted_secret or cursor.rowcount > 0
        self._logger(f"Removed {platform} account credentials; token redacted.")
        return removed

    def account_status(self, platform: str) -> dict[str, str | bool]:
        account = self.get_account(platform)
        return {
            "platform": self._platform(platform),
            "configured": account is not None,
            "username": account.username if account is not None else "",
        }

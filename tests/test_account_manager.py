import json

import pytest

from core.account_manager import AccountManager
from core.secret_store import SecretStore


class FakeBackend:
    def protect(self, data: bytes) -> bytes:
        return b"encrypted:" + data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[len(b"encrypted:") :][::-1]


def test_account_credentials_are_securely_stored_and_retrievable(tmp_path):
    secret_path = tmp_path / "secrets.json"
    secret_store = SecretStore(secret_path, FakeBackend())
    logs = []
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=secret_store,
        logger=logs.append,
    )

    manager.set_account("instagram", "creator", "private-token-123")
    account = manager.get_account("instagram")

    assert account is not None
    assert account.username == "creator"
    assert account.token == "private-token-123"
    assert "private-token-123" not in secret_path.read_text(encoding="utf-8")
    assert "private-token-123" not in repr(account)
    assert all("private-token-123" not in entry for entry in logs)
    assert manager.account_status("instagram") == {
        "platform": "instagram",
        "configured": True,
        "username": "creator",
    }


def test_environment_credentials_are_supported_without_logging_token(tmp_path):
    logs = []
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=SecretStore(tmp_path / "secrets.json", FakeBackend()),
        environ={
            "SOCIAL_TIKTOK_USERNAME": "shorts",
            "SOCIAL_TIKTOK_TOKEN": "env-token-secret",
        },
        logger=logs.append,
    )

    account = manager.get_account("tiktok")

    assert account is not None
    assert account.username == "shorts"
    assert account.token == "env-token-secret"
    assert all("env-token-secret" not in entry for entry in logs)


def test_environment_credentials_work_when_secure_backend_is_unavailable(
    tmp_path, monkeypatch
):
    import core.account_manager as account_manager
    from core.secret_store import SecretBackendError

    def unavailable_store(_path):
        raise SecretBackendError("DPAPI unavailable")

    monkeypatch.setattr(account_manager, "SecretStore", unavailable_store)
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        config_dir=tmp_path / "config",
        environ={
            "SOCIAL_INSTAGRAM_USERNAME": "creator",
            "SOCIAL_INSTAGRAM_TOKEN": "environment-secret",
        },
    )

    assert manager.get_account("instagram").token == "environment-secret"
    with pytest.raises(RuntimeError, match="Secure token storage is unavailable"):
        manager.set_account("instagram", "creator", "new-secret")
    assert "new-secret" not in repr(manager.account_status("instagram"))


def test_partial_environment_credentials_are_rejected(tmp_path):
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=SecretStore(tmp_path / "secrets.json", FakeBackend()),
        environ={"SOCIAL_INSTAGRAM_TOKEN": "secret"},
    )

    with pytest.raises(ValueError, match="Both SOCIAL_INSTAGRAM"):
        manager.get_account("instagram")


def test_account_removal_deletes_secret_and_username(tmp_path):
    secret_store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    manager = AccountManager(tmp_path / "state.sqlite3", secret_store=secret_store)
    manager.set_account("tiktok", "creator", "token")

    assert manager.remove_account("tiktok")
    assert manager.get_account("tiktok") is None
    assert secret_store.get("social:tiktok:token") is None


@pytest.mark.parametrize("platform", ["twitter", ""])
def test_unsupported_social_platform_is_rejected(tmp_path, platform):
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=SecretStore(tmp_path / "secrets.json", FakeBackend()),
    )
    with pytest.raises(ValueError, match="Unsupported"):
        manager.get_account(platform)


def test_account_username_is_only_saved_as_non_secret_metadata(tmp_path):
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=SecretStore(tmp_path / "secrets.json", FakeBackend()),
    )
    manager.set_account("instagram", "public-name", "top-secret")

    with open(tmp_path / "state.sqlite3", "rb") as database:
        contents = database.read()
    assert b"public-name" in contents
    assert b"top-secret" not in contents


def test_secret_store_json_contains_only_encrypted_token_material(tmp_path):
    secret_path = tmp_path / "secrets.json"
    manager = AccountManager(
        tmp_path / "state.sqlite3",
        secret_store=SecretStore(secret_path, FakeBackend()),
    )
    manager.set_account("instagram", "creator", "top-secret")

    data = json.loads(secret_path.read_text(encoding="utf-8"))
    assert list(data) == ["social:instagram:token"]
    assert "top-secret" not in json.dumps(data)

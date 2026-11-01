"""Gemini key lookup and migration into the SecretStore."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import api_keys
from core.secret_store import SecretStore


class FakeBackend:
    def protect(self, data: bytes) -> bytes:
        return data[::-1]

    def unprotect(self, data: bytes) -> bytes:
        return data[::-1]


def _plain(tmp_path: Path, key: str = "plain-key") -> None:
    (tmp_path / "api_keys.json").write_text(
        json.dumps({"gemini_api_key": key, "os_system": "windows"}), encoding="utf-8")


def test_falls_back_to_plain_file(tmp_path, monkeypatch):
    monkeypatch.setattr(api_keys, "_store", lambda d: None)
    _plain(tmp_path)
    assert api_keys.gemini_api_key(tmp_path) == "plain-key"


def test_secret_store_wins_over_plain(tmp_path, monkeypatch):
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    store.set(api_keys.SECRET_NAME, "stored-key")
    monkeypatch.setattr(api_keys, "_store", lambda d: store)
    _plain(tmp_path)
    assert api_keys.gemini_api_key(tmp_path) == "stored-key"


def test_missing_everything_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(api_keys, "_store", lambda d: None)
    assert api_keys.gemini_api_key(tmp_path) == ""


def test_migrate_keeps_plain_by_default(tmp_path):
    _plain(tmp_path)
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    assert api_keys.migrate(tmp_path, store).startswith("migrated")
    assert store.get(api_keys.SECRET_NAME) == "plain-key"
    assert json.loads((tmp_path / "api_keys.json").read_text())["gemini_api_key"] == "plain-key"


def test_migrate_remove_plain_blanks_only_the_key(tmp_path, monkeypatch):
    _plain(tmp_path)
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    api_keys.migrate(tmp_path, store, remove_plain=True)
    data = json.loads((tmp_path / "api_keys.json").read_text())
    assert data == {"gemini_api_key": "", "os_system": "windows"}
    monkeypatch.setattr(api_keys, "_store", lambda d: store)
    assert api_keys.gemini_api_key(tmp_path) == "plain-key"


def test_migrate_without_key_is_an_error(tmp_path):
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    assert api_keys.migrate(tmp_path, store).startswith("error:")


def test_save_gemini_key_goes_to_store_not_plain(tmp_path):
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    assert api_keys.save_gemini_key(tmp_path, "new-key", "windows", store) is True
    assert store.get(api_keys.SECRET_NAME) == "new-key"
    data = json.loads((tmp_path / "api_keys.json").read_text())
    assert data == {"gemini_api_key": "", "os_system": "windows"}
    assert "new-key" not in (tmp_path / "api_keys.json").read_text()
    assert "new-key" not in (tmp_path / "secrets.json").read_text()


def test_save_gemini_key_falls_back_when_store_unavailable(tmp_path):
    class Broken:
        def protect(self, data):
            raise RuntimeError("no backend")

        def unprotect(self, data):
            raise RuntimeError("no backend")

    store = SecretStore(tmp_path / "secrets.json", Broken())
    assert api_keys.save_gemini_key(tmp_path, "k", "linux", store) is False
    assert json.loads((tmp_path / "api_keys.json").read_text())["gemini_api_key"] == "k"


def test_save_gemini_key_preserves_other_settings(tmp_path):
    (tmp_path / "api_keys.json").write_text(json.dumps({"assistant_name": "X"}))
    store = SecretStore(tmp_path / "secrets.json", FakeBackend())
    api_keys.save_gemini_key(tmp_path, "k", "windows", store)
    assert json.loads((tmp_path / "api_keys.json").read_text())["assistant_name"] == "X"

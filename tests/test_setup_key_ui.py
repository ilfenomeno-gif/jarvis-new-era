"""MainWindow._on_setup_done: the plain-text fallback must be visible, not only logged."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import core.api_keys as api_keys
import ui
from core.secret_store import SecretStore


class _Broken:
    def protect(self, data):
        raise RuntimeError("no backend")

    def unprotect(self, data):
        raise RuntimeError("no backend")


class _Reversing:
    def protect(self, data):
        return data[::-1]

    def unprotect(self, data):
        return data[::-1]


def _window(logs, warnings):
    window = SimpleNamespace(
        _log=SimpleNamespace(append_log=logs.append),
        _overlay=None,
        _ready=False,
        _apply_state=lambda _state: None,
        _assistant_name="",
    )
    window._warn_plaintext_key = lambda: warnings.append(True)
    return window


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ui, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ui, "API_FILE", tmp_path / "api_keys.json")
    return tmp_path


def test_secure_save_shows_no_warning(config_dir, monkeypatch):
    store = SecretStore(config_dir / "secrets.json", _Reversing())
    monkeypatch.setattr(api_keys, "SecretStore", lambda path: store)
    logs, warnings = [], []
    window = _window(logs, warnings)

    ui.MainWindow._on_setup_done(window, "secret-key", "windows")

    assert warnings == []
    assert window._ready is True
    assert json.loads((config_dir / "api_keys.json").read_text())["gemini_api_key"] == ""
    assert store.get(api_keys.SECRET_NAME) == "secret-key"


def test_plaintext_fallback_raises_visible_warning(config_dir, monkeypatch):
    store = SecretStore(config_dir / "secrets.json", _Broken())
    monkeypatch.setattr(api_keys, "SecretStore", lambda path: store)
    logs, warnings = [], []
    window = _window(logs, warnings)

    ui.MainWindow._on_setup_done(window, "secret-key", "windows")

    assert warnings == [True]
    assert window._ready is True
    assert json.loads((config_dir / "api_keys.json").read_text())["gemini_api_key"] == "secret-key"


def test_warning_dialog_names_the_file(monkeypatch):
    shown = []
    monkeypatch.setattr(ui.QMessageBox, "warning",
                        staticmethod(lambda *args: shown.append(args)))
    logs = []
    window = SimpleNamespace(_log=SimpleNamespace(append_log=logs.append))

    ui.MainWindow._warn_plaintext_key(window)

    assert logs and "api_keys.json" in logs[0]
    assert shown and "api_keys.json" in shown[0][2]


def test_plaintext_warning_is_explicit_when_fallback_is_enabled(monkeypatch):
    monkeypatch.setenv("JARVIS_ALLOW_PLAINTEXT_KEY", "1")
    shown = []
    monkeypatch.setattr(ui.QMessageBox, "warning",
                        staticmethod(lambda *args: shown.append(args)))
    logs = []
    window = SimpleNamespace(_log=SimpleNamespace(append_log=logs.append))

    ui.MainWindow._warn_plaintext_key(window)

    assert logs and "PLAIN TEXT" in logs[0]
    assert shown and "IN CHIARO" in shown[0][2]

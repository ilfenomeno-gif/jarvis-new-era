"""
Gemini API key lookup: SecretStore first, plain config/api_keys.json as a
backward-compatible fallback. ``migrate`` moves the key into the SecretStore.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.secret_store import SecretStore

SECRET_NAME = "gemini_api_key"
_BASE = Path(__file__).resolve().parents[1]


def _store(config_dir: Path) -> SecretStore | None:
    try:
        return SecretStore(config_dir / "secrets.json")
    except Exception:
        return None


def _read_plain(config_dir: Path) -> str:
    try:
        data = json.loads((config_dir / "api_keys.json").read_text(encoding="utf-8"))
        return str(data.get("gemini_api_key") or "")
    except Exception:
        return ""


def gemini_api_key(config_dir: Path | None = None) -> str:
    """The Gemini key, or "" when none is configured. Never raises."""
    config_dir = Path(config_dir) if config_dir else _BASE / "config"
    store = _store(config_dir)
    if store is not None:
        try:
            value = store.get(SECRET_NAME)
        except Exception:
            value = None
        if value:
            return value
    return _read_plain(config_dir)


def save_gemini_key(config_dir: Path, key: str, os_name: str,
                    store: SecretStore | None = None) -> bool:
    """Persist the key from the setup screen. Returns True when it went into the
    SecretStore; False when no secure backend exists and it was written to
    api_keys.json as before."""
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "api_keys.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data["os_system"] = os_name
    secured = False
    try:
        store = store or SecretStore(config_dir / "secrets.json")
        store.set(SECRET_NAME, key)
        secured = store.get(SECRET_NAME) == key
    except Exception:
        secured = False
    data["gemini_api_key"] = "" if secured else key
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return secured


def migrate(config_dir: Path | None = None, store: SecretStore | None = None,
            remove_plain: bool = False) -> str:
    """Copy the plain-text key into the SecretStore. With ``remove_plain`` the
    plain-text value is blanked only after the stored copy reads back intact."""
    config_dir = Path(config_dir) if config_dir else _BASE / "config"
    store = store or SecretStore(config_dir / "secrets.json")
    key = _read_plain(config_dir)
    if not key:
        if store.get(SECRET_NAME):
            return "already migrated"
        return "error: no gemini_api_key found in api_keys.json"
    store.set(SECRET_NAME, key)
    if store.get(SECRET_NAME) != key:
        return "error: stored key failed to read back; plain-text file left untouched"
    if remove_plain:
        path = config_dir / "api_keys.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["gemini_api_key"] = ""
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        return "migrated; plain-text key removed"
    return "migrated; plain-text key kept (use --remove-plain to blank it)"

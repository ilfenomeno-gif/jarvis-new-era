"""
Secret storage for connector tokens and API keys.

Secrets never live in plain text on disk. The default backend encrypts each
value with Windows DPAPI (bound to the current user) and stores the ciphertext
in ``config/secrets.json``. Other platforms must inject a backend explicitly;
there is deliberately no plain-text fallback.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from typing import Protocol


class SecretBackendError(RuntimeError):
    pass


class SecretBackend(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class DpapiBackend:
    """Windows Data Protection API, scoped to the current user."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise SecretBackendError("DPAPI is only available on Windows.")

    @staticmethod
    def _call(fn_name: str, data: bytes) -> bytes:
        import ctypes
        from ctypes import wintypes

        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        buffer = ctypes.create_string_buffer(data, len(data))
        source = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        target = DataBlob()
        fn = getattr(ctypes.windll.crypt32, fn_name)
        if not fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
            raise SecretBackendError(f"{fn_name} failed.")
        try:
            return ctypes.string_at(target.pbData, target.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(target.pbData)

    def protect(self, data: bytes) -> bytes:
        return self._call("CryptProtectData", data)

    def unprotect(self, data: bytes) -> bytes:
        return self._call("CryptUnprotectData", data)


class SecretStore:
    def __init__(self, path: Path, backend: SecretBackend | None = None) -> None:
        self._path = Path(path)
        self._backend = backend if backend is not None else DpapiBackend()

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def set(self, key: str, value: str) -> None:
        if not key:
            raise ValueError("Secret key must not be empty.")
        token = self._backend.protect(value.encode("utf-8"))
        data = self._load()
        data[key] = base64.b64encode(token).decode("ascii")
        self._save(data)

    def get(self, key: str) -> str | None:
        encoded = self._load().get(key)
        if encoded is None:
            return None
        try:
            return self._backend.unprotect(base64.b64decode(encoded)).decode("utf-8")
        except Exception:
            return None

    def delete(self, key: str) -> bool:
        data = self._load()
        if key not in data:
            return False
        del data[key]
        self._save(data)
        return True

    def keys(self) -> list[str]:
        return sorted(self._load())

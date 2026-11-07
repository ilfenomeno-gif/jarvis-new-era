"""Clipboard helpers shared by terminal and browser computer-use actions."""

from __future__ import annotations

import base64
import os
import subprocess
from collections.abc import Callable
from typing import Any, Protocol


class ClipboardBackend(Protocol):
    def get(self) -> str: ...
    def set(self, text: str) -> None: ...


class _PowerShellClipboard:
    @staticmethod
    def _run(script: str) -> str:
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    encoded,
                ],
                check=False,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"PowerShell clipboard access failed: {exc}") from exc
        if result.returncode:
            detail = result.stderr.strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"PowerShell clipboard access failed: {detail}")
        return result.stdout

    def get(self) -> str:
        if os.name != "nt":
            raise RuntimeError("System clipboard access requires Windows.")
        return self._run(
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$value = Get-Clipboard -Raw; "
            "if ($null -ne $value) { [Console]::Out.Write($value) }"
        )

    def set(self, text: str) -> None:
        if os.name != "nt":
            raise RuntimeError("System clipboard access requires Windows.")
        value = base64.b64encode(text.encode("utf-8")).decode("ascii")
        self._run(
            "$value = [System.Text.Encoding]::UTF8.GetString("
            f"[System.Convert]::FromBase64String('{value}')); "
            "Set-Clipboard -Value $value"
        )


_backend: ClipboardBackend = _PowerShellClipboard()


def set_backend(backend: ClipboardBackend) -> ClipboardBackend:
    """Replace the system backend and return the previous one (primarily for tests)."""
    global _backend
    previous, _backend = _backend, backend
    return previous


def get() -> str:
    return _backend.get()


def set(text: str) -> None:
    if not isinstance(text, str):
        raise TypeError("Clipboard content must be text.")
    _backend.set(text)


def copy_selection(browser: Any = None) -> str:
    if browser is None:
        return get()
    copy = getattr(browser, "copy_selection", None)
    if not callable(copy):
        raise TypeError("browser must provide copy_selection().")
    text = copy()
    if not isinstance(text, str):
        raise TypeError("Browser selection must be text.")
    set(text)
    return text


def paste_into(
    target: str | Callable[[str], None] | Any,
    *,
    browser: Any = None,
) -> None:
    text = get()
    if browser is not None:
        paste = getattr(browser, "paste_text", None)
        if not callable(paste) or not isinstance(target, str):
            raise TypeError("Browser paste requires a selector and paste_text().")
        paste(target, text)
        return
    if callable(target):
        target(text)
        return
    type_text = getattr(target, "type_text", None)
    if callable(type_text):
        type_text(text)
        return
    raise TypeError("Terminal paste target must be callable or provide type_text().")

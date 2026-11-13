"""Launch URLs in the user's normal Google Chrome profile."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from core.browser_url import normalize_http_url


def find_chrome_executable() -> Path:
    configured = os.environ.get("JARVIS_CHROME_PATH")
    candidates = [Path(configured)] if configured else []
    if platform.system() == "Windows":
        for root in (
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ):
            if root:
                candidates.append(
                    Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe"
                )
    else:
        from shutil import which

        for name in ("google-chrome", "chrome", "chromium", "chromium-browser"):
            executable = which(name)
            if executable:
                candidates.append(Path(executable))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "Chrome was not found. Install Google Chrome or set JARVIS_CHROME_PATH."
    )


def open_chrome_url(
    url: str, *, executable_path: str | Path | None = None
) -> subprocess.Popen:
    """Open an HTTP(S) URL in Chrome without overriding its profile or window mode."""
    normalized_url = normalize_http_url(url)
    chrome = Path(executable_path) if executable_path else find_chrome_executable()
    if not chrome.is_file():
        raise FileNotFoundError(f"Chrome executable does not exist: {chrome}")
    return subprocess.Popen(
        [str(chrome), normalized_url],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

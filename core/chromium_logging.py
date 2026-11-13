"""Configure Chromium's native logging before Qt WebEngine initializes."""
from __future__ import annotations

import os
import re


def configure_chromium_logging() -> None:
    if (os.environ.get("JARVIS_LOG_LEGACY") == "1"
            or os.environ.get("JARVIS_LOG_DIAGNOSTIC", "1") != "1"
            or os.environ.get("JARVIS_LOG_VERBOSE") == "1"):
        return
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if not re.search(r"(?:^|\s)--log-level(?:=|\s|$)", flags):
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (flags + " --log-level=3").strip()

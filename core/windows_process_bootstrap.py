"""Configure Windows console output and subprocess window behavior."""

from __future__ import annotations

import platform
import subprocess
import sys
from contextlib import suppress

for stream_name in ("stdout", "stderr"):
    with suppress(Exception):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

if platform.system() == "Windows":
    _original_popen = subprocess.Popen

    class _NoConsolePopen(_original_popen):
        def __init__(self, args, **kwargs):
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
            )
            kwargs.pop("startupinfo", None)
            super().__init__(args, **kwargs)

    subprocess.Popen = _NoConsolePopen

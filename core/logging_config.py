"""Environment-driven logging configuration for the desktop runtime."""
from __future__ import annotations

import logging
import os


def configure_logging(level: str | None = None) -> int:
    configured = (level or os.environ.get("JARVIS_LOG_LEVEL", "INFO")).upper()
    resolved = logging.getLevelName(configured)
    if not isinstance(resolved, int):
        raise ValueError(f"Invalid JARVIS_LOG_LEVEL: {configured!r}")

    logging.basicConfig(
        level=resolved,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s "
        "%(threadName)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.getLogger().setLevel(resolved)
    return resolved

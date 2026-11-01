"""
Utility condivise tra i plugin di JARVIS.

Il nome inizia con '_' quindi `core/plugin_loader.py` lo salta durante la
discovery (non e un plugin), ma essendo dentro il package `plugins`
(che ha un __init__.py) puo essere importato normalmente dagli altri file
plugin con `from plugins._plugin_utils import ...`.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"


def today_str() -> str:
    return date.today().isoformat()


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def atomic_write_json(path: Path, data) -> None:
    """Scrive un file JSON in modo atomico (tmp file + os.replace) per evitare
    di corrompere lo stato se JARVIS viene chiuso a metà scrittura."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

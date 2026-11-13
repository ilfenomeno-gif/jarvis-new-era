"""Read a user-captured Chromium stderr log."""
from collections import deque
from pathlib import Path

from core.logging_config import RedactSensitiveFilter

CHROMIUM_LOG = Path(__file__).resolve().parent.parent / "logs" / "chromium_stderr.log"


def read_chromium_errors(parameters: dict) -> str:
    if not CHROMIUM_LOG.is_file():
        return (
            "Il log Chromium non è disponibile. La modalità diagnostica silenzia "
            "i messaggi nativi; per acquisirli abilita JARVIS_LOG_VERBOSE e "
            "reindirizza stderr nel file chromium_stderr.log."
        )
    with CHROMIUM_LOG.open(encoding="utf-8", errors="replace") as stream:
        lines = deque(stream, maxlen=20)
    if not lines:
        return "Il log Chromium è vuoto."
    return "Ultime righe del log Chromium:\n" + RedactSensitiveFilter._redact("".join(lines)).rstrip()


TOOL = {
    "name": "read_chromium_errors",
    "description": "Legge le ultime 20 righe del log Chromium acquisito localmente.",
    "risk_class": "read",
    "parameters": {"type": "OBJECT", "properties": {}},
    "handler": read_chromium_errors,
}

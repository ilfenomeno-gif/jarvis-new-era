"""Local clipboard history. Clipboard contents must never enter model prompts."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from core.guardrails import redact_sensitive

_LOG = logging.getLogger(__name__)
HISTORY_PATH = Path(__file__).resolve().parent.parent / "config" / "clipboard_history.json"
_LIMIT = 10 * 1024


def classify(text: str) -> str:
    value = text.strip()
    if re.match(r"^https?://\S+$", value, re.I):
        return "url"
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return "email"
    if re.match(r"^(?:[a-z]:\\|\\\\)", value, re.I):
        return "path"
    try:
        if value.startswith(("{", "[")) and isinstance(json.loads(value), (dict, list)):
            return "json"
    except ValueError:
        pass
    if re.search(r"\b(?:def|function)\s+\w+|[{}]", value):
        return "code"
    return "text"


class ClipboardIntelligence:
    def __init__(self, *, path: Path | None = None, reader=None, writer=None,
                 sequence_reader=None, interval: float = 0.5):
        if interval <= 0:
            raise ValueError("Intervallo clipboard non valido.")
        self.path = Path(path) if path is not None else HISTORY_PATH
        self._reader = reader
        self._writer = writer
        self._sequence_reader = sequence_reader
        self._interval = interval
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._last = None
        self._items = self._load()

    def _load(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, list) or not all(
            isinstance(item, dict) and isinstance(item.get("content"), str)
            and isinstance(item.get("type"), str) and isinstance(item.get("timestamp"), str)
            for item in data
        ):
            raise ValueError("Cronologia clipboard non valida.")
        return data[-100:]

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".clipboard-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(self._items, file, ensure_ascii=False)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def capture(self, text: str) -> bool:
        if not isinstance(text, str) or not text:
            return False
        encoded = text[:_LIMIT].encode("utf-8")[:_LIMIT]
        content = encoded.decode("utf-8", errors="ignore")
        digest = hashlib.sha256(content.encode("utf-8")).digest()
        if digest == self._last:
            return False
        self._last = digest
        if redact_sensitive(content) != content:
            _LOG.warning("[SYMBIOSIS][CLIPBOARD] Elemento potenzialmente sensibile escluso")
            return False
        entry = {"timestamp": datetime.now(UTC).isoformat(),
                 "content": content, "type": classify(content)}
        with self._lock:
            previous = self._items
            self._items = (previous + [entry])[-100:]
            try:
                self._save()
            except (OSError, ValueError):
                self._items = previous
                self._last = None
                raise
        return True

    def get_history(self, limit: int = 100, category: str | None = None) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ValueError("Limite non valido.")
        with self._lock:
            values = [item.copy() for item in reversed(self._items)
                      if category is None or item["type"] == category]
        return values[:limit]

    def search(self, query: str) -> list[dict]:
        if not query:
            raise ValueError("Ricerca vuota.")
        return [item for item in self.get_history() if query.casefold() in item["content"].casefold()]

    def get_last(self) -> dict | None:
        items = self.get_history(1)
        return items[0] if items else None

    def restore(self, index: int) -> None:
        items = self.get_history()
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(items):
            raise ValueError("Indice clipboard non valido.")
        writer = self._writer
        if writer is None:
            import pyperclip
            writer = pyperclip.copy
        writer(items[index]["content"])
        self._last = hashlib.sha256(items[index]["content"].encode("utf-8")).digest()

    def clear(self) -> None:
        with self._lock:
            previous = self._items
            self._items = []
            try:
                self._save()
            except (OSError, ValueError):
                self._items = previous
                raise

    def metadata(self, limit: int = 10) -> list[dict]:
        return [{"timestamp": item["timestamp"], "type": item["type"],
                 "length": len(item["content"])} for item in self.get_history(limit)]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        _LOG.warning("[SYMBIOSIS][CLIPBOARD] La cronologia locale non è cifrata; il filtro segreti è parziale")
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="symbiosis-clipboard", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            if self._reader is None:
                import pyperclip
                self._reader = pyperclip.paste
            if self._sequence_reader is None and os.name == "nt":
                try:
                    import win32clipboard
                    self._sequence_reader = win32clipboard.GetClipboardSequenceNumber
                except (ImportError, AttributeError):
                    _LOG.warning("[SYMBIOSIS][CLIPBOARD] Notifiche clipboard non disponibili; uso polling")
            sequence = None
            while not self._stop.is_set():
                try:
                    current = self._sequence_reader() if self._sequence_reader else None
                    if self._sequence_reader is None or current != sequence:
                        self.capture(self._reader())
                        sequence = current
                except Exception:
                    _LOG.exception("[SYMBIOSIS][CLIPBOARD] Lettura o salvataggio non riusciti")
                self._stop.wait(self._interval)
        except ImportError:
            _LOG.exception("[SYMBIOSIS][CLIPBOARD] Dipendenza non disponibile")

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise TimeoutError("Il thread clipboard non si è arrestato.")

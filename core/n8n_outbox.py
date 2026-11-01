"""n8n outbox polling — n8n → desktop events WITHOUT opening any inbound port.

WHY POLLING AND NOT A LISTENER
    The desktop is behind NAT and the rule for JARVIS VII is "no port opened to
    the internet". So n8n cannot push. Instead n8n appends events to an
    "outbox" workflow (a Webhook that returns the pending events as JSON), and
    this module polls it on a timer over HTTPS with the same auth header as the
    bridge. Outbound-only is preserved.

CONFIGURATION — same file as the bridge, config/n8n.json (git-ignored):

    {
      "base_url": "https://<instance>.app.n8n.cloud",
      "webhook_path": "/webhook/jarvis-bridge",
      "auth_header": "X-Jarvis-Token",
      "outbox": {
        "enabled": true,
        "webhook_path": "/webhook/jarvis-outbox",
        "interval_sec": 60
      }
    }

    The outbox webhook is expected to answer a GET/POST with a JSON body that is
    either a list of events or {"events": [...]}. Each event is a small dict;
    recognised fields: "text" (what to show/say), "id" (for de-duplication).

SECURITY
    Same SecretStore entry as the bridge ("n8n:webhook"). Events are text shown
    on the HUD / spoken — they are DATA, wrapped with outcome.untrusted before
    being handed anywhere the model could read them, and never executed.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from core import outcome

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config" / "n8n.json"
_DEFAULT_INTERVAL = 60.0
_MAX_EVENTS_PER_POLL = 20


def _load_outbox_config(path: Path = CONFIG_PATH) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out = data.get("outbox")
    return dict(out) if isinstance(out, dict) else {}


class OutboxPoller:
    """Polls the n8n outbox webhook on a daemon thread.

    on_event: callable(text: str) invoked for each new event (e.g. HUD say/log).
    secrets:  object with .get(key) — the DPAPI SecretStore.
    """

    def __init__(self, on_event: Callable[[str], None], secrets,
                 *, config_path: Path = CONFIG_PATH,
                 http_post=None, audit=None):
        self._on_event = on_event
        self._secrets = secrets
        self._config_path = Path(config_path)
        self._http_post = http_post          # injectable for tests
        self._audit = audit
        self._seen: set[str] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ── config ──────────────────────────────────────────────────────────────
    def _settings(self) -> dict:
        cfg = _load_outbox_config(self._config_path)
        if not cfg.get("enabled"):
            return {}
        try:
            base_cfg = json.loads(self._config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        base = str(base_cfg.get("base_url") or "").strip().rstrip("/")
        header = str(base_cfg.get("auth_header") or "").strip()
        path = str(cfg.get("webhook_path") or "").strip()
        if not (base.startswith("https://") and header and path):
            return {}
        if not path.startswith("/"):
            path = "/" + path
        return {
            "url": base + path,
            "header": header,
            "interval": float(cfg.get("interval_sec", _DEFAULT_INTERVAL)),
        }

    # ── HTTP (injectable) ───────────────────────────────────────────────────
    def _fetch(self, url: str, header: str) -> list[dict]:
        secret = self._secrets.get("n8n:webhook") if self._secrets else None
        if not secret:
            return []
        if self._http_post is not None:
            body = self._http_post(url, {header: secret})
        else:
            import httpx
            with httpx.Client(timeout=15.0, follow_redirects=False) as client:
                resp = client.post(url, json={"poll": True}, headers={header: secret})
                if resp.status_code != 200:
                    return []
                body = resp.text
        return self._parse_events(body)

    @staticmethod
    def _parse_events(body) -> list[dict]:
        if isinstance(body, (bytes, bytearray)):
            body = body.decode("utf-8", "replace")
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except json.JSONDecodeError:
                return []
        if isinstance(body, dict):
            body = body.get("events", [])
        if not isinstance(body, list):
            return []
        # Keep only dict events that carry some text, then cap the count.
        events = [e for e in body
                  if isinstance(e, dict) and str(e.get("text") or "").strip()]
        return events[:_MAX_EVENTS_PER_POLL]

    # ── polling loop ────────────────────────────────────────────────────────
    def poll_once(self) -> int:
        """One poll. Returns the number of NEW events delivered."""
        settings = self._settings()
        if not settings:
            return 0
        try:
            events = self._fetch(settings["url"], settings["header"])
        except Exception as exc:
            if self._audit:
                self._audit.record(tool="n8n_outbox", outcome="failed",
                                   detail=type(exc).__name__)
            return 0
        delivered = 0
        for event in events:
            text = str(event.get("text") or "").strip()
            if not text:
                continue
            eid = str(event.get("id") or text)
            if eid in self._seen:
                continue
            self._seen.add(eid)
            delivered += 1
            if self._audit:
                self._audit.record(tool="n8n_outbox", outcome="done",
                                   detail="event", arguments={"id": eid})
            try:
                # The HUD/log shows the text as-is (a person asked for it). The
                # untrusted wrapper is applied only where the MODEL could read
                # the event — see outcome.untrusted at the call sites that hand
                # events to the conversation.
                self._on_event(text)
            except Exception:
                pass
        return delivered

    def start(self) -> bool:
        """Start the background loop. Returns False when not configured."""
        settings = self._settings()
        if not settings or self._thread is not None:
            return False
        interval = settings["interval"]

        def _loop():
            while not self._stop.is_set():
                try:
                    self.poll_once()
                except Exception:
                    pass
                self._stop.wait(interval)

        self._thread = threading.Thread(target=_loop, name="n8n-outbox", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

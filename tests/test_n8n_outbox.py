"""Tests for the n8n outbox poller (P3). HTTP is injected — no network, no real
n8n. Covers: disabled/unconfigured, event parsing shapes, de-duplication,
untrusted-marker handling, audit, and the polling loop start/stop."""
from __future__ import annotations

import json

import pytest

from core import n8n_outbox as ob


class _FakeSecrets:
    def __init__(self, value="tok"):
        self._v = value

    def get(self, key):
        return self._v if key == "n8n:webhook" else None


class _FakeAudit:
    def __init__(self):
        self.records = []

    def record(self, **kw):
        self.records.append(kw)
        return kw


def _write_config(tmp_path, outbox):
    cfg = {
        "base_url": "https://jarvis9090.app.n8n.cloud",
        "webhook_path": "/webhook/jarvis-bridge",
        "auth_header": "X-Jarvis-Token",
        "outbox": outbox,
    }
    p = tmp_path / "n8n.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _poller(tmp_path, events_body, on_event, audit=None):
    cfg = _write_config(tmp_path, {"enabled": True,
                                   "webhook_path": "/webhook/jarvis-outbox",
                                   "interval_sec": 1})
    return ob.OutboxPoller(on_event, _FakeSecrets(), config_path=cfg,
                           http_post=lambda url, headers: events_body,
                           audit=audit)


def test_disabled_when_no_outbox(tmp_path):
    cfg = _write_config(tmp_path, {})
    p = ob.OutboxPoller(lambda t: None, _FakeSecrets(), config_path=cfg,
                        http_post=lambda u, h: [])
    assert p.poll_once() == 0
    assert p.start() is False


def test_events_list_shape(tmp_path):
    got = []
    body = json.dumps([{"id": "1", "text": "new mail"}, {"id": "2", "text": "reminder"}])
    p = _poller(tmp_path, body, got.append)
    assert p.poll_once() == 2
    assert got == ["new mail", "reminder"]


def test_events_dict_shape(tmp_path):
    got = []
    body = json.dumps({"events": [{"text": "hello"}]})
    p = _poller(tmp_path, body, got.append)
    assert p.poll_once() == 1
    assert got == ["hello"]


def test_dedup_by_id(tmp_path):
    got = []
    body = json.dumps([{"id": "x", "text": "same"}])
    p = _poller(tmp_path, body, got.append)
    assert p.poll_once() == 1
    assert p.poll_once() == 0   # second poll: already seen
    assert got == ["same"]


def test_skips_empty_and_caps_count(tmp_path):
    got = []
    events = [{"text": ""}] + [{"id": str(i), "text": f"e{i}"} for i in range(30)]
    p = _poller(tmp_path, json.dumps(events), got.append)
    assert p.poll_once() == ob._MAX_EVENTS_PER_POLL
    assert "" not in got


def test_malformed_body_yields_nothing(tmp_path):
    got = []
    p = _poller(tmp_path, "not json", got.append)
    assert p.poll_once() == 0


def test_event_text_shown_asis_and_untrusted_wrap_available(tmp_path):
    got = []
    body = json.dumps([{"id": "1", "text": "real content"}])
    p = _poller(tmp_path, body, got.append)
    p.poll_once()
    # HUD/log get the plain text (a person asked for it)…
    assert got == ["real content"]
    # …and the untrusted wrapper is available for model-bound text
    wrapped = ob.outcome.untrusted("n8n", got[0])
    assert "UNTRUSTED" in wrapped
    assert ob.outcome.unwrap(wrapped) == "real content"


def test_audit_records_events(tmp_path):
    audit = _FakeAudit()
    body = json.dumps([{"id": "1", "text": "x"}])
    p = _poller(tmp_path, body, lambda t: None, audit=audit)
    p.poll_once()
    assert any(r["outcome"] == "done" and r["tool"] == "n8n_outbox" for r in audit.records)


def test_fetch_error_audited_not_raised(tmp_path):
    audit = _FakeAudit()
    cfg = _write_config(tmp_path, {"enabled": True, "webhook_path": "/webhook/o"})

    def boom(url, headers):
        raise ConnectionError("down")

    p = ob.OutboxPoller(lambda t: None, _FakeSecrets(), config_path=cfg,
                        http_post=boom, audit=audit)
    assert p.poll_once() == 0
    assert any(r["outcome"] == "failed" for r in audit.records)


def test_start_stop_loop(tmp_path):
    got = []
    body = json.dumps([{"id": "1", "text": "tick"}])
    p = _poller(tmp_path, body, got.append)
    assert p.start() is True
    import time
    time.sleep(0.3)
    p.stop()
    assert got  # at least one poll happened

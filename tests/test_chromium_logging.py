import os

from actions import read_chromium_errors
from core.chromium_logging import configure_chromium_logging
from core.tool_router import ToolRouter


def test_default_preserves_flags_and_is_idempotent(monkeypatch):
    monkeypatch.delenv("JARVIS_LOG_LEGACY", raising=False)
    monkeypatch.delenv("JARVIS_LOG_DIAGNOSTIC", raising=False)
    monkeypatch.delenv("JARVIS_LOG_VERBOSE", raising=False)
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--use-gl=angle")
    configure_chromium_logging()
    configure_chromium_logging()
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == "--use-gl=angle --log-level=3"


def test_explicit_level_and_legacy_are_preserved(monkeypatch):
    monkeypatch.delenv("JARVIS_LOG_LEGACY", raising=False)
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--log-level=0")
    configure_chromium_logging()
    assert os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] == "--log-level=0"
    monkeypatch.setenv("JARVIS_LOG_LEGACY", "1")
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS")
    configure_chromium_logging()
    assert "QTWEBENGINE_CHROMIUM_FLAGS" not in os.environ


def test_read_last_twenty_lines_and_redact(tmp_path, monkeypatch):
    log = tmp_path / "chromium_stderr.log"
    monkeypatch.setattr(read_chromium_errors, "CHROMIUM_LOG", log)
    assert "non è disponibile" in read_chromium_errors.read_chromium_errors({})
    log.write_text("".join(f"line {number}\n" for number in range(25)) + "token=secret\n", encoding="utf-8")
    result = read_chromium_errors.read_chromium_errors({})
    assert "line 5\n" not in result and "line 6\n" in result
    assert "secret" not in result and "[REDACTED]" in result
    assert len(result.splitlines()) == 21


def test_voice_router_selects_chromium_reader():
    selected = ToolRouter().select_for_request(
        "Jarvis, leggi gli errori di Chromium", [{"name": "read_chromium_errors"}]
    )
    assert [item["name"] for item in selected] == ["read_chromium_errors"]

import logging

import pytest

from core.logging_config import configure_logging
from core.timing import timed


def test_timed_records_deterministic_duration(fake_clock, caplog):
    logger = logging.getLogger("test.latency")
    caplog.set_level(logging.INFO, logger="test.latency")

    with timed(logger, "llm.first_token", clock=fake_clock):
        fake_clock.advance(0.125)

    assert "stage=llm.first_token status=ok duration_ms=125.000" in caplog.text


def test_timed_logs_failure_duration_and_reraises(fake_clock, caplog):
    logger = logging.getLogger("test.latency.failure")
    caplog.set_level(logging.ERROR, logger="test.latency.failure")

    with pytest.raises(RuntimeError, match="provider failed"), timed(
        logger, "tts.synthesize", clock=fake_clock
    ):
        fake_clock.advance(0.25)
        raise RuntimeError("provider failed")

    assert "stage=tts.synthesize status=error duration_ms=250.000" in caplog.text
    assert "RuntimeError: provider failed" in caplog.text


def test_logging_level_is_configurable_and_invalid_values_are_rejected(monkeypatch):
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "level", root_logger.level)
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "DEBUG")
    assert configure_logging() == logging.DEBUG

    with pytest.raises(ValueError, match="JARVIS_LOG_LEVEL"):
        configure_logging("NOT_A_LEVEL")

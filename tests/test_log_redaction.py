import io
import logging

import pytest

from core.logging_config import (
    RedactSensitiveFilter,
    configure_logging,
    install_redaction_filter,
)


def _captured_log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    install_redaction_filter(handler)
    logger = logging.getLogger(f"test.redaction.{id(stream)}")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, handler, stream


def test_redacts_authorization_header():
    logger, handler, stream = _captured_log()
    credential = "x" * 32
    try:
        logger.debug("%s: %s %s", "Authorization", "Bearer", credential)

        output = stream.getvalue()
        assert credential not in output
        assert "Authorization: [REDACTED]" in output
    finally:
        logger.removeHandler(handler)
        handler.close()


@pytest.mark.parametrize(
    "header",
    ["authorization", "X-API-Key", "Api-Key", "bEaReR", "Cookie", "Set-Cookie"],
)
def test_redacts_sensitive_headers_case_insensitively(header):
    logger, handler, stream = _captured_log()
    credential = "v" * 32
    try:
        logger.debug("%s: %s", header, credential)

        assert credential not in stream.getvalue()
        assert "[REDACTED]" in stream.getvalue()
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_redacts_long_base64_payload():
    logger, handler, stream = _captured_log()
    payload = "Q" * 220
    try:
        logger.debug("encoded=%s", payload)

        output = stream.getvalue()
        assert payload not in output
        assert "[REDACTED]" in output
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_redacts_sensitive_payload_fields():
    logger, handler, stream = _captured_log()
    payload = (
        '{"audio":"voice-data","pcm":"sample-data","image":"frame-data",'
        '"token":"token-value","api_key":"key-value",'
        '"password":"password-value","secret":"secret-value"}'
    )
    try:
        logger.debug("%s", payload)

        output = stream.getvalue()
        for value in (
            "voice-data",
            "sample-data",
            "frame-data",
            "token-value",
            "key-value",
            "password-value",
            "secret-value",
        ):
            assert value not in output
        assert output.count("[REDACTED]") == 7
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_normal_log_message_passes_unchanged():
    logger, handler, stream = _captured_log()
    try:
        logger.info("runtime started")

        assert stream.getvalue() == "runtime started\n"
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_configure_logging_filters_existing_named_logger_handlers(monkeypatch):
    logger, handler, stream = _captured_log()
    original_level = logging.getLogger().level
    try:
        configure_logging("INFO")
        assert any(isinstance(item, RedactSensitiveFilter) for item in handler.filters)

        logger.info("api_key=still-secret")
        assert "still-secret" not in stream.getvalue()
    finally:
        logging.getLogger().setLevel(original_level)
        logger.removeHandler(handler)
        handler.close()

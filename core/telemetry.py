"""Shared OpenTelemetry helpers for runtime spans."""
from __future__ import annotations

from opentelemetry.trace import Span, Status, StatusCode


def record_span_error(span: Span, error: Exception) -> None:
    span.record_exception(error)
    span.set_attribute("error.type", type(error).__name__)
    span.set_status(Status(StatusCode.ERROR, type(error).__name__))

"""Human-readable and JSON Lines diagnostic formatters."""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from uuid import uuid4

NOTICE = 25
logging.addLevelName(NOTICE, "NOTICE")
SESSION_ID = uuid4().hex
_COMPONENTS = {"core.network_security": "symbiosis.network"}


def component_for(record: logging.LogRecord) -> str:
    return getattr(record, "component", None) or _COMPONENTS.get(record.name, record.name)


class DiagnosticFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        message = record.getMessage()
        if hasattr(record, "throttled_count"):
            message += f" (throttled: {record.throttled_count})"
        result = f"[{timestamp}.{int(record.msecs):03d}] [{record.levelname}] [{component_for(record)}] {message}"
        values = [(key, getattr(record, key)) for key in ("context", "impact", "action")
                  if getattr(record, key, None) is not None]
        for index, (key, value) in enumerate(values):
            marker = "└─" if index == len(values) - 1 else "├─"
            result += f"\n{marker} {key}: {json.dumps(value, ensure_ascii=False, default=str)}"
        if record.exc_info:
            result += "\n" + self.formatException(record.exc_info)
        if record.stack_info:
            result += "\n" + self.formatStack(record.stack_info)
        return result


class JSONFormatter(logging.Formatter):
    def __init__(self, session_id: str = SESSION_ID):
        super().__init__()
        self.session_id = session_id

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        data = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "component": component_for(record),
            "message": message,
            "context": getattr(record, "context", None),
            "impact": getattr(record, "impact", None),
            "action": getattr(record, "action", None),
            "pid": record.process or os.getpid(),
            "thread": record.threadName,
            "session_id": self.session_id,
        }
        if hasattr(record, "throttled_count"):
            data["throttled_count"] = record.throttled_count
        return json.dumps(data, ensure_ascii=False, default=str)

"""Neutral contracts shared by the Jarvis application and its adapters."""

from capabilities.computer import DesktopInput, ScreenElement, ScreenVision, WebSearch
from capabilities.contracts import OutcomeStatus, ToolCall, ToolReply

__all__ = [
    "DesktopInput",
    "OutcomeStatus",
    "ScreenElement",
    "ScreenVision",
    "ToolCall",
    "ToolReply",
    "WebSearch",
]

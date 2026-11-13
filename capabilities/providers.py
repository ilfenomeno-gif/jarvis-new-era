"""Compatibility exports for the provider protocols currently used by Jarvis.

The definitions remain in ``providers.base`` so existing provider modules and
callers keep the same protocol objects while new code can depend on this
capability-facing import path.
"""

from providers.base import LLM, STT, TTS, Engine, FunctionCall

__all__ = ["Engine", "FunctionCall", "LLM", "STT", "TTS"]

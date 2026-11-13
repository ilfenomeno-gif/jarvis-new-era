"""Require the facade-owned process module without starting background services."""

from core import process_master


def available() -> bool:
    return process_master.get_service() is not None


UNAVAILABLE = "Process mastery is unavailable: the facade or process module is not active."

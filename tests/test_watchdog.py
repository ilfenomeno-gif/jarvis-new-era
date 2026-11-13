from __future__ import annotations

import threading

import pytest

from core.watchdog import ProcessWatchdog


def test_watchdog_recovers_only_registered_owned_process():
    recovered = threading.Event()
    logs = []
    healthy = {"value": False}
    watchdog = ProcessWatchdog(interval=0.01, logger=logs.append)
    watchdog.register(
        "owned-mcp-child",
        lambda: healthy["value"],
        lambda: (healthy.update(value=True), recovered.set()),
    )
    watchdog.start()
    try:
        assert recovered.wait(1)
        assert logs and "owned-mcp-child" in logs[0]
    finally:
        watchdog.stop()

    assert not watchdog._thread or not watchdog._thread.is_alive()


def test_watchdog_logs_health_and_recovery_errors():
    logs = []
    recovery_attempted = threading.Event()

    def failed_recovery():
        recovery_attempted.set()
        raise RuntimeError("recovery failed")

    watchdog = ProcessWatchdog(interval=0.01, logger=logs.append)
    watchdog.register(
        "failing-owned-child",
        lambda: False,
        failed_recovery,
    )
    watchdog.start()
    try:
        assert recovery_attempted.wait(1)
    finally:
        watchdog.stop()

    assert any("Recovery failed" in line for line in logs)


def test_watchdog_validates_registration_and_interval():
    with pytest.raises(ValueError, match="positive"):
        ProcessWatchdog(interval=0)

    watchdog = ProcessWatchdog()
    with pytest.raises(ValueError, match="name"):
        watchdog.register(" ", lambda: True, lambda: None)

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from core.log_throttler import LogThrottler


def test_levels_and_summary(caplog):
    throttler = LogThrottler()
    key = str(uuid4())
    assert throttler.should_log(key, "WARN")
    for _ in range(10):
        assert not throttler.should_log(key, "WARN")
    assert throttler.should_log(key, "ERROR")
    assert not throttler.should_log(key, "ERROR")
    assert throttler.should_log(key, "INFO")
    assert throttler.should_log(key, "CRITICAL")
    with caplog.at_level(25):
        assert throttler.flush_summary()[key] == 11
    assert key in caplog.text
    assert throttler.get_count(key) == 0


def test_concurrent_record():
    throttler = LogThrottler()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(throttler.record, [key] * 1000))
    assert throttler.get_count(key) == 1000
    throttler.flush_summary()


def test_qualified_burst_survives_until_flush(monkeypatch):
    from core import log_throttler

    now = [1000.0]
    monkeypatch.setattr(log_throttler.time, "monotonic", lambda: now[0])
    throttler = LogThrottler()
    key = str(uuid4())
    for _ in range(10):
        throttler.record(key)
    now[0] += 301
    throttler.record(key)
    assert throttler.flush_summary()[key] == 11


def test_default_intervals(monkeypatch):
    from core import log_throttler

    now = [1000.0]
    monkeypatch.setattr(log_throttler.time, "monotonic", lambda: now[0])
    throttler = LogThrottler()
    key = str(uuid4())
    for level, ttl in (("WARN", 30), ("ERROR", 5), ("NOTICE", 60)):
        assert throttler.should_log(key, level)
        now[0] += ttl - 1
        assert not throttler.should_log(key, level)
        now[0] += 1
        assert throttler.should_log(key, level)


def test_concurrent_should_log_allows_only_one():
    throttler = LogThrottler()
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: throttler.should_log(key, "WARNING"), range(100)))
    assert sum(results) == 1
    assert throttler.get_count(key) == 99
    throttler.flush_summary()

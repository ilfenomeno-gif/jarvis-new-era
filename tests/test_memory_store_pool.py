import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.memory_store import MemoryStore


@pytest.mark.parametrize("pooled", [False, True])
def test_memory_store_preserves_behavior_with_and_without_persistent_connection(
    tmp_path,
    monkeypatch,
    pooled,
):
    monkeypatch.setenv("JARVIS_MEMORY_POOL", "1" if pooled else "0")
    database = tmp_path / "memory.sqlite3"
    store = MemoryStore(database)
    try:
        store.remember("session", "state", {"step": 2})
        store.save_record("plan", "one", {"items": ["a", "b"]})
        store.record_event("session:1", "saved", {"ok": True})

        assert store.recall("session", "state") == {"step": 2}
        assert store.load_record("plan", "one") == {"items": ["a", "b"]}
        events = store.list_events("session:")
        assert len(events) == 1
        assert {key: events[0][key] for key in ("event_key", "event_type", "payload")} == {
            "event_key": "session:1",
            "event_type": "saved",
            "payload": {"ok": True},
        }
        checkpoint_id = store.checkpoint()
        assert store.resume(checkpoint_id) == {
            "memory": [{"scope": "session", "key": "state", "value": {"step": 2}}]
        }

        if pooled:
            entry = store._thread_connections.entry
            connection = entry.connection
            assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
            assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
            store.recall("session", "state")
            assert store._thread_connections.entry is entry
        else:
            assert store._pool_connections == {}
    finally:
        store.close()

    restarted = MemoryStore(database)
    try:
        assert restarted.recall("session", "state") == {"step": 2}
    finally:
        restarted.close()


@pytest.mark.parametrize("pooled", [False, True])
def test_memory_store_handles_concurrent_calls(tmp_path, monkeypatch, pooled):
    monkeypatch.setenv("JARVIS_MEMORY_POOL", "1" if pooled else "0")
    store = MemoryStore(tmp_path / "concurrent.sqlite3")
    try:
        def remember(index):
            key = f"parallel-{index}"
            store.remember("session", key, {"index": index})
            return store.recall("session", key)

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(remember, range(64)))

        assert results == [{"index": index} for index in range(64)]
    finally:
        store.close()


def test_memory_store_pool_uses_one_connection_per_thread(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_MEMORY_POOL", "1")
    store = MemoryStore(tmp_path / "thread-local.sqlite3")
    barrier = threading.Barrier(4)

    def connection_id(_index):
        with store._connection() as connection:
            barrier.wait(timeout=5)
            return id(connection)

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            connections = list(executor.map(connection_id, range(4)))
        assert len(set(connections)) == 4
        assert len(store._pool_connections) == 5
    finally:
        store.close()

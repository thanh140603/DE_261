"""The BR1/BR3 benchmark must not destroy the demo state it borrows."""

from __future__ import annotations

from benchmarks.br123_latency import (
    DEDUP_KEY,
    INBOX_KEY,
    drop_created_notifications,
    restore_notifications,
    snapshot_notifications,
)

from tests.unit.contexts.test_redis_adapters import FakeRedis


def test_benchmark_snapshot_restores_the_learner_inbox() -> None:
    store = FakeRedis()
    store.rpush(INBOX_KEY, "newest", "old")
    store.strings[DEDUP_KEY] = "1"
    store.pttls[DEDUP_KEY] = 5000
    snapshot = snapshot_notifications(store)

    store.delete(INBOX_KEY)  # the harness measures on an empty inbox
    store.lpush(INBOX_KEY, "benchmark-note")
    store.strings["edu:notif:item:benchmark-note"] = "{}"
    store.set(DEDUP_KEY, "2")

    restore_notifications(store, snapshot)

    assert store.lists[INBOX_KEY] == ["newest", "old"]
    assert store.strings[DEDUP_KEY] == "1"
    assert store.pttls[DEDUP_KEY] == 5000
    assert "edu:notif:item:benchmark-note" not in store.strings


def test_benchmark_drops_only_the_sample_notification() -> None:
    store = FakeRedis()
    store.rpush(INBOX_KEY, "baseline")
    store.lpush(INBOX_KEY, "sample")
    store.strings["edu:notif:item:sample"] = "{}"

    drop_created_notifications(store, {"baseline"})

    assert store.lists[INBOX_KEY] == ["baseline"]
    assert "edu:notif:item:sample" not in store.strings

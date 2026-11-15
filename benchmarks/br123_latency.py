"""Measure BR1--BR3 end-to-end latency against the running service stack.

BR1: LMS event -> notification readable through the API.
BR2: recommendation request with the online feature store.
BR3: submission accepted (202) and submission -> graded.

The stack must be up (``docker compose -f docker-compose.yml -f
docker-compose.br13.yml up -d``).

The reported BR1 number is measured on an *empty* inbox, because the API returns the whole list
and a growing list would inflate the poll cost. The harness no longer deletes the learner's real
inbox: it snapshots the inbox + dedup key before the run, empties the inbox for the measurement,
and restores the snapshot afterwards (including on error). Each sample removes only the
notification it created.

BR3 no longer wipes ``edu:grading:*``: the attempt sequence is an O(1) counter, so each sample
just resets that counter. The submissions created by the run are removed from Redis afterwards
(their Postgres projection is the same as any other graded submission and is kept for analysis).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx
import redis

DEDUP_KEY = "edu:notif:dedup:l-002:lms.deadline_approaching.v1:a-py-even"
INBOX_KEY = "edu:notif:inbox:l-002"
# The counter now makes the attempt lookup O(1); resetting this one key preserves the demo
# grading history while every sample still starts at attempt 1 (see 05-danh-gia).
ATTEMPT_KEY = "edu:grading:attempts:l-002:a-py-even"


TIMELINE_KEY = "edu:notif:time:l-002"


def _item_key(notification_id: str) -> str:
    return f"edu:notif:item:{notification_id}"


def _forget(store: redis.Redis, notification_id: str) -> None:
    """Remove one benchmark notification from the list, the timeline ZSET and the event index."""
    raw = store.get(_item_key(notification_id))
    store.lrem(INBOX_KEY, 0, notification_id)
    store.zrem(TIMELINE_KEY, notification_id)
    store.delete(_item_key(notification_id))
    if raw is not None:
        store.delete(f"edu:notif:event:{json.loads(raw)['source_event_id']}")


def snapshot_notifications(store: redis.Redis) -> dict[str, Any]:
    """Save the learner's real inbox + dedup state before the harness empties it."""
    return {
        "inbox": list(store.lrange(INBOX_KEY, 0, -1)),
        "dedup": store.get(DEDUP_KEY),
        "dedup_ttl_ms": store.pttl(DEDUP_KEY),
    }


def restore_notifications(store: redis.Redis, snapshot: dict[str, Any]) -> None:
    """Drop everything the run created and put the original inbox back."""
    original = set(snapshot["inbox"])
    for notification_id in store.lrange(INBOX_KEY, 0, -1):
        if notification_id not in original:
            _forget(store, notification_id)
    for notification_id in store.zrange(TIMELINE_KEY, 0, -1):
        if notification_id not in original:
            store.zrem(TIMELINE_KEY, notification_id)
    store.delete(INBOX_KEY)
    if original:
        store.rpush(INBOX_KEY, *snapshot["inbox"])
    dedup = snapshot["dedup"]
    if dedup is None:
        store.delete(DEDUP_KEY)
        return
    ttl = int(snapshot["dedup_ttl_ms"])
    if ttl > 0:
        store.set(DEDUP_KEY, dedup, px=ttl)
    else:
        store.set(DEDUP_KEY, dedup)


def drop_created_notifications(store: redis.Redis, baseline: set[str]) -> None:
    """Remove the notification produced by one sample, keeping the inbox at its baseline."""
    for notification_id in store.lrange(INBOX_KEY, 0, -1):
        if notification_id not in baseline:
            _forget(store, notification_id)


def wait_dispatched(store: redis.Redis, baseline: set[str], timeout: float = 2.0) -> None:
    """Wait for the second save before deleting a sample's notification.

    RouteEvent saves the notification (it is readable from then on, which is what BR1 times);
    DispatchNotification saves it again after email/push with ``SET NX``. Deleting the item in
    between would let that second save re-create it and push it back into the inbox, where the
    next sample would count it as its own.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = False
        for notification_id in store.lrange(INBOX_KEY, 0, -1):
            raw = None if notification_id in baseline else store.get(_item_key(notification_id))
            if raw is not None:
                item = json.loads(raw)
                pending = pending or bool(item["channels"] and not item["dispatched"])
        if not pending:
            return
        time.sleep(0.005)
    raise RuntimeError("BR1 notification was not dispatched in time; are mailpit and push-sink up?")


def cleanup_submissions(store: redis.Redis, submission_ids: list[str]) -> None:
    """Drop the benchmark's own submissions from the hot store; durable copies stay in Postgres."""
    timeline = "edu:grading:timeline:l-002"
    for submission_id in submission_ids:
        store.delete(
            f"edu:grading:submission:{submission_id}",
            f"edu:grading:code:{submission_id}",
            f"edu:grading:worker:{submission_id}",
        )
        store.zrem(timeline, submission_id)
        store.srem("edu:grading:submissions", submission_id)
        for result_key in store.scan_iter(match=f"edu:grading:result:{submission_id}:*"):
            store.delete(result_key)


CODE = "def sum_even(xs):\n    return sum(x for x in xs if x % 2 == 0)\n"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]


def summary(name: str, values: list[float]) -> str:
    return (
        f"{name}: n={len(values)} median={statistics.median(values):.1f} ms "
        f"p90={percentile(values, 0.90):.1f} ms "
        f"min={min(values):.1f} ms max={max(values):.1f} ms"
    )


def measure_br1(client: httpx.Client, store: redis.Redis, samples: int) -> list[float]:
    client.post("/api/learners/l-002/enroll", json={"course_id": "c-ml-301"}).raise_for_status()
    baseline = set(store.lrange(INBOX_KEY, 0, -1))  # empty: main emptied the inbox for the run

    def once() -> float:
        drop_created_notifications(store, baseline)  # sweep strays before counting
        store.delete(DEDUP_KEY)
        before = len(client.get("/api/learners/l-002/notifications").json())
        started = time.perf_counter()
        response = client.post(
            "/api/simulate/lms-event",
            json={
                "event_type": "deadline_approaching",
                "course_id": "c-ml-301",
                "assignment_id": "a-py-even",
                "learner_id": "l-002",
                "hours_to_deadline": 6,
            },
        )
        response.raise_for_status()
        for _ in range(1000):
            rows = client.get("/api/learners/l-002/notifications").json()
            if len(rows) > before:
                elapsed = (time.perf_counter() - started) * 1000
                wait_dispatched(store, baseline)
                drop_created_notifications(store, baseline)
                return elapsed
            time.sleep(0.002)
        raise RuntimeError("BR1 notification did not appear")

    once()  # warm-up: first Kafka produce/consume after service start is slower
    return [once() for _ in range(samples)]


def measure_br2(client: httpx.Client, samples: int) -> list[float]:
    for _ in range(3):
        client.get("/api/learners/l-002/recommendations").raise_for_status()
    values = []
    for _ in range(samples):
        started = time.perf_counter()
        client.get("/api/learners/l-002/recommendations").raise_for_status()
        values.append((time.perf_counter() - started) * 1000)
    return values


def measure_br3(
    client: httpx.Client, store: redis.Redis, samples: int
) -> tuple[list[float], list[float], list[str]]:
    created: list[str] = []

    def once() -> tuple[float, float]:
        store.set(ATTEMPT_KEY, 0)  # attempt 1 again; keeps the learner's history intact
        started = time.perf_counter()
        response = client.post(
            "/api/submissions",
            json={"learner_id": "l-002", "assignment_id": "a-py-even", "code": CODE},
        )
        response.raise_for_status()
        accepted = (time.perf_counter() - started) * 1000
        submission_id = response.json()["submission_id"]
        created.append(submission_id)
        for _ in range(4000):
            row = client.get(f"/api/submissions/{submission_id}").json()
            if row["status"] in {"graded", "failed"}:
                return accepted, (time.perf_counter() - started) * 1000
            time.sleep(0.003)
        raise RuntimeError(f"submission {submission_id} did not finish grading")

    once()  # warm-up: first Kafka produce and sandbox process are slower
    acks: list[float] = []
    totals: list[float] = []
    for _ in range(samples):
        ack, total = once()
        acks.append(ack)
        totals.append(total)
    return acks, totals, created


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--br2-samples", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("report/data/br123_latency.csv"))
    args = parser.parse_args()

    store = redis.Redis.from_url(args.redis_url, decode_responses=True)
    snapshot = snapshot_notifications(store)
    attempt_before = store.get(ATTEMPT_KEY)
    created_submissions: list[str] = []
    try:
        store.delete(INBOX_KEY)  # measurement conditions: an empty inbox, restored in finally
        with httpx.Client(base_url=args.base_url, timeout=60) as client:
            br1 = measure_br1(client, store, args.samples)
            br2 = measure_br2(client, args.br2_samples)
            br3_ack, br3_total, created_submissions = measure_br3(client, store, args.samples)
    finally:
        cleanup_submissions(store, created_submissions)
        if attempt_before is None:
            store.delete(ATTEMPT_KEY)
        else:
            store.set(ATTEMPT_KEY, attempt_before)
        restore_notifications(store, snapshot)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "metric", "run", "latency_ms"])
        for run, value in enumerate(br1, 1):
            writer.writerow(["BR1", "event_to_inbox", run, f"{value:.3f}"])
        for run, value in enumerate(br2, 1):
            writer.writerow(["BR2", "recommendations_api", run, f"{value:.3f}"])
        for run, (ack, total) in enumerate(zip(br3_ack, br3_total, strict=True), 1):
            writer.writerow(["BR3", "submit_ack", run, f"{ack:.3f}"])
            writer.writerow(["BR3", "submit_to_graded", run, f"{total:.3f}"])

    print(summary("BR1 event -> inbox", br1))
    print(summary("BR2 recommendations API", br2))
    print(summary("BR3 submit -> 202", br3_ack))
    print(summary("BR3 submit -> graded", br3_total))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

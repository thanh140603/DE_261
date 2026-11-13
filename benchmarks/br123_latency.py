"""Measure BR1--BR3 end-to-end latency against the running service stack.

BR1: LMS event -> notification readable through the API.
BR2: recommendation request with the online feature store.
BR3: submission accepted (202) and submission -> graded.

The stack must be up (``docker compose -f docker-compose.yml -f
docker-compose.br13.yml up -d``). Each BR1 sample removes the dedup key and the learner inbox so
the same deadline event produces a fresh notification without inflating the poll cost; each BR3
sample clears the Redis grading state so the attempt count does not grow with the demo history.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import time
from pathlib import Path

import httpx
import redis

DEDUP_KEY = "edu:notif:dedup:l-002:lms.deadline_approaching.v1:a-py-even"
# Each BR1 sample starts from an empty inbox: the API returns the whole inbox, so a growing
# list would inflate the poll cost and make successive runs incomparable (see 05-danh-gia).
INBOX_KEY = "edu:notif:inbox:l-002"
# BR3's attempt_number is computed by scanning every submission of the learner, so the ack path
# would grow with the demo history. Each sample starts from an empty grading state (see 05-danh-gia).
GRADING_PATTERN = "edu:grading:*"


def reset_grading(store: redis.Redis) -> None:
    keys = list(store.scan_iter(GRADING_PATTERN))
    if keys:
        store.delete(*keys)
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

    def once() -> float:
        store.delete(DEDUP_KEY, INBOX_KEY)  # isolate the sample: no dedup, no growing inbox
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
                return (time.perf_counter() - started) * 1000
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


def measure_br3(client: httpx.Client, store: redis.Redis, samples: int) -> tuple[list[float], list[float]]:
    def once() -> tuple[float, float]:
        reset_grading(store)
        started = time.perf_counter()
        response = client.post(
            "/api/submissions",
            json={"learner_id": "l-002", "assignment_id": "a-py-even", "code": CODE},
        )
        response.raise_for_status()
        accepted = (time.perf_counter() - started) * 1000
        submission_id = response.json()["submission_id"]
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
    return acks, totals


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--br2-samples", type=int, default=30)
    parser.add_argument("--out", type=Path, default=Path("report/data/br123_latency.csv"))
    args = parser.parse_args()

    store = redis.Redis.from_url(args.redis_url, decode_responses=True)
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        br1 = measure_br1(client, store, args.samples)
        br2 = measure_br2(client, args.br2_samples)
        br3_ack, br3_total = measure_br3(client, store, args.samples)

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

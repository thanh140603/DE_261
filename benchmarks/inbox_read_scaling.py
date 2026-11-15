"""BR1: latency đọc inbox theo số thông báo, cho báo cáo.

Seed N notification tổng hợp cho một learner thử (mặc định l-004), đo API full inbox và
?limit=20, ghi CSV, rồi dọn sạch. Không dùng l-002 để tránh phá dữ liệu demo.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import redis

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_repository import (
    _to_dict,
)

LEARNER = "l-004"


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]


def seed(store: redis.Redis, learner: str, n: int) -> None:
    inbox = f"edu:notif:inbox:{learner}"
    timeline = f"edu:notif:time:{learner}"
    store.delete(inbox, timeline)
    base = datetime.now(tz=UTC) - timedelta(minutes=10)
    pipe = store.pipeline(transaction=False)
    for i in range(n):
        nid = f"bench-{i:03d}"
        notification = Notification(
            id=nid,
            recipient_id=learner,
            dedup_key=DedupKey(learner, "lms.deadline_approaching.v1", f"bench-{i}"),
            channels=(Channel.IN_APP,),
            priority=Priority.NORMAL,
            content=NotificationContent(
                f"Due in {i} h: ML Engineering",
                "Submit before the deadline to keep your streak. " * 5,
                "/learner",
            ),
            source_event_id=f"bench-event-{i}",
            source_event_type="lms.deadline_approaching.v1",
            created_at=base + timedelta(seconds=i),
        )
        raw = json.dumps(_to_dict(notification), separators=(",", ":"))
        pipe.set(f"edu:notif:item:{nid}", raw, ex=3600)
        pipe.zadd(timeline, {nid: int(notification.created_at.timestamp() * 1_000_000)})
        pipe.lpush(inbox, nid)  # created_at tăng dần -> mới nhất ở đầu list
    pipe.execute()
    store.expire(inbox, 3600)
    store.expire(timeline, 3600)


def cleanup(store: redis.Redis, learner: str, n: int) -> None:
    pipe = store.pipeline(transaction=False)
    for i in range(n):
        pipe.delete(f"edu:notif:item:bench-{i:03d}")
    pipe.delete(f"edu:notif:inbox:{learner}", f"edu:notif:time:{learner}")
    pipe.execute()


def measure(client: httpx.Client, learner: str, reps: int) -> tuple[float, float, float, float]:
    full_url = f"/api/learners/{learner}/notifications"
    page_url = f"/api/learners/{learner}/notifications?limit=20"
    for _ in range(5):
        client.get(full_url)
        client.get(page_url)

    full: list[float] = []
    page: list[float] = []
    for _ in range(reps):
        for url, bucket in ((full_url, full), (page_url, page)):
            started = time.perf_counter()
            response = client.get(url)
            response.raise_for_status()
            bucket.append((time.perf_counter() - started) * 1000)
    return (
        statistics.median(full),
        percentile(full, 0.9),
        statistics.median(page),
        percentile(page, 0.9),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--redis-url", default="redis://localhost:6379/0")
    parser.add_argument("--learner", default=LEARNER)
    parser.add_argument("--sizes", default="0,10,25,50,100,150,200")
    parser.add_argument("--reps", type=int, default=200)
    parser.add_argument("--out", type=Path, default=Path("report/data/br1_inbox_scaling.csv"))
    args = parser.parse_args()

    sizes = [int(part) for part in args.sizes.split(",") if part.strip()]
    store = redis.Redis.from_url(args.redis_url, decode_responses=True)
    inbox = f"edu:notif:inbox:{args.learner}"
    if store.llen(inbox):
        depth = store.llen(inbox)
        raise SystemExit(f"{args.learner} đang có {depth} thông báo; chọn learner trống")

    rows: list[tuple[int, str, float, float]] = []
    try:
        with httpx.Client(base_url=args.base_url, timeout=30) as client:
            for n in sizes:
                seed(store, args.learner, n)
                try:
                    full = client.get(f"/api/learners/{args.learner}/notifications").json()
                    page = client.get(f"/api/learners/{args.learner}/notifications?limit=20").json()
                    if len(full) != n or len(page) != min(20, n):
                        raise SystemExit(f"n={n}: full={len(full)} page={len(page)}, expected")
                    full_p50, full_p90, page_p50, page_p90 = measure(
                        client, args.learner, args.reps
                    )
                    rows.append((n, "full", full_p50, full_p90))
                    rows.append((n, "limit20", page_p50, page_p90))
                    print(
                        f"n={n:3d} full {full_p50:6.2f}/{full_p90:6.2f} ms  "
                        f"limit20 {page_p50:6.2f}/{page_p90:6.2f} ms"
                    )
                finally:
                    cleanup(store, args.learner, n)
    finally:
        cleanup(store, args.learner, max(sizes))
        print(f"{args.learner} inbox còn:", store.llen(inbox))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        handle.write("inbox_size,path,p50_ms,p90_ms\n")
        for n, path, p50, p90 in rows:
            handle.write(f"{n},{path},{p50:.3f},{p90:.3f}\n")
    print("wrote", args.out)

    # In tọa độ cho pgfplots (dùng p50 trong hình; p90 dùng cho câu văn)
    for path in ("full", "limit20"):
        points = [f"({n},{p50:.2f})" for n, p, p50, _ in rows if p == path]
        print(path, " ".join(points))


if __name__ == "__main__":
    main()

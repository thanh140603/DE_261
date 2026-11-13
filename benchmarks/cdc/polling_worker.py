"""Incremental updated_at polling worker (the downgrade baseline)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import psycopg

from benchmarks.cdc.metrics import summarize, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default="postgresql://lms:lms@localhost:5433/lms")
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(updated_at) FROM bench.cdc_source")
        watermark = cur.fetchone()[0]

    events: list[dict[str, object]] = []
    query_ms: list[float] = []
    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        started = time.perf_counter()
        with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, updated_at FROM bench.cdc_source "
                "WHERE updated_at > %s ORDER BY updated_at",
                (watermark,),
            )
            rows = cur.fetchall()
        query_ms.append((time.perf_counter() - started) * 1000)
        for row_id, changed_at in rows:
            events.append(
                {
                    "id": row_id,
                    "observed_at": time.time(),
                    "source_updated_at": changed_at.timestamp(),
                    "latency_ms": (time.time() - changed_at.timestamp()) * 1000,
                }
            )
            watermark = changed_at
        time.sleep(args.interval)

    payload = {
        "engine": "polling",
        "events": len(events),
        "updates": len(events),
        "deletes": 0,
        "query_count": len(query_ms),
        "query_ms": summarize(query_ms),
        "latency_ms": summarize([float(event["latency_ms"]) for event in events]),
        "sample": events[:5],
    }
    write_json(args.out, payload)
    print(json.dumps({k: v for k, v in payload.items() if k != "sample"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

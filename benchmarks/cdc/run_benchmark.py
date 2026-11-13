"""Run the Debezium-vs-polling benchmark and emit a result JSON."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from benchmarks.cdc.metrics import write_json


def db_counters(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT xact_commit, tup_returned FROM pg_stat_database "
            "WHERE datname = current_database()"
        )
        xact, tuples = cur.fetchone()
    return {"xact_commit": int(xact), "tup_returned": int(tuples)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default="postgresql://lms:lms@localhost:5433/lms")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--updates", type=int, default=100)
    parser.add_argument("--deletes", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("benchmarks/cdc/results/cdc_100k.json"))
    args = parser.parse_args()

    out_dir = args.out.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    polling_out = out_dir / "polling_worker.json"
    debezium_out = out_dir / "debezium_worker.json"
    before = db_counters(args.dsn)

    ready = debezium_out.with_suffix(debezium_out.suffix + ".ready")
    ready.unlink(missing_ok=True)

    polling = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "benchmarks.cdc.polling_worker",
            "--duration",
            str(args.duration),
            "--out",
            str(polling_out),
        ]
    )
    debezium = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "benchmarks.cdc.debezium_consumer",
            "--duration",
            str(args.duration),
            "--group",
            f"bench-cdc-{int(time.time())}",
            "--out",
            str(debezium_out),
        ]
    )
    deadline = time.monotonic() + 15
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    time.sleep(0.5)

    started = time.perf_counter()
    with psycopg.connect(args.dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE bench.cdc_source SET score = score + 1, updated_at = clock_timestamp() "
            "WHERE id IN (SELECT id FROM bench.cdc_source ORDER BY id LIMIT %s)",
            (args.updates,),
        )
        cur.execute(
            "DELETE FROM bench.cdc_source WHERE id IN "
            "(SELECT id FROM bench.cdc_source ORDER BY id DESC LIMIT %s)",
            (args.deletes,),
        )
        conn.commit()
    operation_s = time.perf_counter() - started

    polling.wait(timeout=args.duration + 20)
    debezium.wait(timeout=args.duration + 20)
    after = db_counters(args.dsn)

    polling_result = json.loads(polling_out.read_text())
    debezium_result = json.loads(debezium_out.read_text())
    payload = {
        "source_rows": 100_000,
        "updates": args.updates,
        "deletes": args.deletes,
        "operation_s": round(operation_s, 3),
        "polling": polling_result,
        "debezium": debezium_result,
        "db_counters": {"before": before, "after": after},
        "correctness": {
            "debezium_updates": debezium_result["updates"],
            "polling_updates": polling_result["updates"],
            "debezium_deletes": debezium_result["deletes"],
            "polling_deletes": polling_result["deletes"],
        },
    }
    write_json(args.out, payload)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generate deterministic organisation-progress facts for the OLAP benchmark.

CSV is used because it loads directly through PostgreSQL COPY and StarRocks
Stream Load, keeping the comparison focused on the serving engine rather than
on two different file readers.

Example:
    .venv/bin/python benchmarks/cdc/generate_facts.py \
      --size-gb 5 \
      --output benchmarks/cdc/data/org-facts-5gb.csv
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = "olap-bench/v1"
ORGS = ("org-acme", "org-globex")
COURSES = (
    "c-sql-101",
    "c-py-201",
    "c-de-301",
    "c-ml-301",
    "c-dl-401",
    "c-mlops-501",
)
START = datetime(2026, 10, 1, tzinfo=UTC)
DATES = tuple((START + timedelta(days=i)).date().isoformat() for i in range(41))
HEADER = (
    "fact_id,org_id,learner_pseudonym,course_id,enrollment_id,event_date,completed,score,mastery\n"
)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024.0
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-gb", type=float, default=5.0, help="target size in GiB")
    parser.add_argument("--rows", type=int, default=0, help="exact row count; overrides --size-gb")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/cdc/data/org-facts-5gb.csv"),
        help="output CSV path",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.size_gb <= 0 and args.rows <= 0:
        parser.error("--size-gb must be positive (or pass --rows)")
    if args.rows < 0:
        parser.error("--rows must be non-negative")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists() and not args.force:
        parser.error(f"{args.output} already exists; pass --force to overwrite")

    target = int(args.size_gb * 1024**3) if args.rows <= 0 else 0
    started = time.monotonic()
    rows = written = 0
    rng = random.Random(args.seed)

    with args.output.open("wb", buffering=1024 * 1024) as out:
        header = HEADER.encode("ascii")
        out.write(header)
        written += len(header)
        while True:
            if target and written >= target:
                break
            if args.rows and rows >= args.rows:
                break
            learner = rng.randrange(2_000_000)
            course = rng.choice(COURSES)
            line = (
                f"f_{rows:024x},{rng.choice(ORGS)},k1_{learner:024x},{course},"
                f"e_{rng.randrange(1_000_000_000):016x},{rng.choice(DATES)},"
                f"{1 if rng.random() < 0.42 else 0},{rng.uniform(0.0, 1.0):.4f},"
                f"{rng.uniform(0.0, 1.0):.4f}\n"
            ).encode("ascii")
            out.write(line)
            written += len(line)
            rows += 1
            if rows % 1_000_000 == 0:
                elapsed = max(time.monotonic() - started, 1e-9)
                print(
                    f"rows={rows:,} size={_human_bytes(written)} rate={rows / elapsed:,.0f} rows/s",
                    file=sys.stderr,
                    flush=True,
                )

    elapsed = max(time.monotonic() - started, 1e-9)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "seed": args.seed,
        "target_bytes": target,
        "target_gib": args.size_gb if args.rows <= 0 else None,
        "requested_rows": args.rows or None,
        "rows": rows,
        "bytes": written,
        "file": str(args.output),
        "elapsed_seconds": round(elapsed, 3),
        "rows_per_second": round(rows / elapsed, 1),
        "generated_at": datetime.now(UTC).isoformat(),
        "note": "CSV is stopped at the target size; the final line is complete.",
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(_json_dump(manifest))
    print(_json_dump(manifest))
    return 0


def _json_dump(manifest: dict[str, object]) -> str:
    import json

    return json.dumps(manifest, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())

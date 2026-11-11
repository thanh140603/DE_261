"""Generate deterministic feature-store rows for the Redis/ScyllaDB benchmark.

The output is JSON Lines: one JSON object per learner, streamed so a 5 GiB
file never has to fit in memory. It is intentionally a local benchmark tool,
not a production data generator.

Example:
    PYTHONPATH=. .venv/bin/python \
      benchmarks/alternatives/feature_store/generate_features.py \
      --size-gb 5 \
      --output benchmarks/alternatives/data/features-5gb.jsonl

The file is stopped after the target size is reached; the last JSON line is
always complete, so the actual size is target + at most one row.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "feature-store-bench/v1"
PLATFORMS = ("web", "mobile")
VERBS = ("play", "pause", "seek", "complete", "submit", "view")
COURSES = (
    "c-sql-101",
    "c-py-201",
    "c-de-301",
    "c-ml-301",
    "c-dl-401",
    "c-mlops-501",
)


def _row(rng: random.Random, index: int) -> dict[str, Any]:
    """Build one deterministic, realistic-shaped feature row."""
    completion = round(rng.uniform(0.0, 1.0), 4)
    pass_rate = round(rng.uniform(0.0, 1.0), 4)
    return {
        "learner_pseudonym": f"k1_{index:024x}",
        "completion_rate_30d": completion,
        "avg_pass_rate_30d": pass_rate,
        "active_days_30d": rng.randint(0, 30),
        "preferred_platform": rng.choice(PLATFORMS),
        "skill_mastery": {
            "general": round(rng.uniform(0.0, 1.0), 4),
            "sql": round(rng.uniform(0.0, 1.0), 4),
            "python": round(rng.uniform(0.0, 1.0), 4),
        },
        "computed_at": "2026-11-10T00:00:00",
        "session": {
            "events_in_session": rng.randint(0, 80),
            "active_minutes": round(rng.uniform(0.0, 90.0), 2),
            "last_verbs": [rng.choice(VERBS) for _ in range(rng.randint(0, 3))],
            "current_course_id": rng.choice(COURSES),
        },
    }


def _human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024.0
    raise AssertionError("unreachable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--size-gb", type=float, default=5.0, help="target size in GiB (default: 5)"
    )
    parser.add_argument("--rows", type=int, default=0, help="exact row count; overrides --size-gb")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/alternatives/data/features-5gb.jsonl"),
        help="output JSONL path",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
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
    rows = 0
    written = 0
    rng = random.Random(args.seed)

    with args.output.open("wb", buffering=1024 * 1024) as out:
        while True:
            if target and written >= target:
                break
            if args.rows and rows >= args.rows:
                break
            payload = _row(rng, rows)
            line = (json.dumps(payload, separators=(",", ":"), ensure_ascii=True) + "\n").encode(
                "utf-8"
            )
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
        "note": "JSONL is stopped at the target size; the final line is complete.",
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

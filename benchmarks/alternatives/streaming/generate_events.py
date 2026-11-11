"""Generate deterministic learning events for the Spark vs Flink benchmark.

Output is JSON Lines, streamed to disk. It intentionally uses the same
BR5-shaped event fields (learner pseudonym, course, event time, verb) so both
engines can consume one file without a second schema.

Example:
    .venv/bin/python benchmarks/alternatives/streaming/generate_events.py \
      --size-gb 5 \
      --output benchmarks/alternatives/data/events-5gb.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "streaming-bench/v1"
COURSES = (
    "c-sql-101",
    "c-py-201",
    "c-de-301",
    "c-ml-301",
    "c-dl-401",
    "c-mlops-501",
)
EVENT_TYPES = (
    ("lesson_progress", "complete", 5),
    ("video_play", "play", 4),
    ("quiz_submit", "submit", 3),
    ("submission", "submit", 2),
    ("login", "view", 1),
)
PLATFORMS = ("web", "mobile")
START = datetime(2026, 10, 1, tzinfo=UTC)
SPAN_SECONDS = 40 * 24 * 60 * 60


def _row(rng: random.Random, index: int) -> dict[str, Any]:
    event_type, verb, _ = rng.choices(EVENT_TYPES, weights=[w for _, _, w in EVENT_TYPES], k=1)[0]
    learner = rng.randrange(100_000)
    session = rng.randrange(1_000_000)
    return {
        "event_id": f"evt_{index:024x}",
        "learner_pseudonym": f"k1_{learner:024x}",
        "course_id": rng.choice(COURSES),
        "event_type": event_type,
        "verb": verb,
        "occurred_at": (START + timedelta(seconds=rng.randrange(SPAN_SECONDS))).isoformat(),
        "session_id": f"s_{session:016x}",
        "platform": rng.choice(PLATFORMS),
        "duration_ms": rng.randint(100, 90_000),
        "score": round(rng.uniform(0.0, 1.0), 4),
        "progress": round(rng.uniform(0.0, 1.0), 4),
    }


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
        default=Path("benchmarks/alternatives/data/events-5gb.jsonl"),
        help="output JSONL path",
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
        while True:
            if target and written >= target:
                break
            if args.rows and rows >= args.rows:
                break
            line = (
                json.dumps(_row(rng, rows), separators=(",", ":"), ensure_ascii=True) + "\n"
            ).encode("utf-8")
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

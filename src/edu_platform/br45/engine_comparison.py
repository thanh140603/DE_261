"""Summarize matched engine trials for the dashboard from their raw journals."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

SCALES = (1000, 10000, 100000)
ENGINES = {"BR4": ("postgres", "spark"), "BR5": ("spark", "flink")}
E2E = {"BR4": ("e2e_correction",), "BR5": ("e2e_alert", "e2e_recovery")}


def summarize(journals: list[dict[str, Any]]) -> dict[str, Any]:
    indexed = {(journal["suite"], journal["engine"]): journal for journal in journals}
    if len(indexed) != len(journals):
        raise ValueError("Supply one journal per suite and engine")
    result: dict[str, Any] = {"schema_version": 1}
    for suite, engines in ENGINES.items():
        processing = []
        end_to_end = []
        metadata = []
        for engine in engines:
            journal = indexed.get((suite, engine), {})
            trials = journal.get("trials", [])
            metadata.append(
                {
                    "engine": engine,
                    **{
                        key: journal.get(key)
                        for key in (
                            "run_id",
                            "engine_version",
                            "measured_at",
                            "poll_seconds",
                            "cpu_limit",
                            "memory_limit_gib",
                            "publish_interval_seconds",
                            "flink_checkpoint_seconds",
                        )
                    },
                    "checks": [row for row in trials if row["phase"] in {"correctness", "restart"}],
                }
            )
            for records in SCALES:
                processing.append(group(trials, engine, "processing", records, 3))
            for phase in E2E[suite]:
                end_to_end.append(group(trials, engine, phase, 106 if suite == "BR4" else 4, 5))
        result[suite.lower()] = {
            "processing": sorted(processing, key=lambda row: row["records"]),
            "end_to_end": sorted(end_to_end, key=lambda row: row["phase"]),
            "metadata": metadata,
        }
    return result


def group(
    trials: list[dict[str, Any]],
    engine: str,
    phase: str,
    records: int,
    planned: int,
) -> dict[str, Any]:
    matching = [row for row in trials if row["phase"] == phase and row["records"] == records]
    counts = Counter(row["status"] for row in matching)
    counts["NOT_RUN"] = max(0, planned - len(matching))
    passed = [row for row in matching if row["status"] == "PASS"]
    durations = [row["elapsed_ms"] for row in passed]
    throughput = [row["events_per_second"] for row in passed if "events_per_second" in row]
    return {
        "engine": engine,
        "phase": phase,
        "records": records,
        "planned": planned,
        "statuses": {status: count for status, count in counts.items() if count},
        "median_ms": median(durations) if durations else None,
        "min_ms": min(durations) if durations else None,
        "max_ms": max(durations) if durations else None,
        "median_events_per_second": median(throughput) if throughput else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("journals", nargs="+", type=Path)
    args = parser.parse_args()
    data = summarize([json.loads(path.read_text()) for path in args.journals])
    draft = args.output.with_suffix(".tmp")
    draft.write_text(json.dumps(data, indent=2) + "\n")
    draft.replace(args.output)


if __name__ == "__main__":
    main()

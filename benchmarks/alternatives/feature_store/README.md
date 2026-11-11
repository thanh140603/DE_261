# Feature-store benchmark data

Local generator for the Redis vs ScyllaDB/Cassandra benchmark. It streams
JSON Lines so a multi-GB dataset never has to fit in memory.

## Generate 5 GiB

```bash
.venv/bin/python benchmarks/alternatives/feature_store/generate_features.py \
  --size-gb 5 \
  --output benchmarks/alternatives/data/features-5gb.jsonl
```

The generator stops once the target is reached and always finishes the last
JSON line. Actual size is therefore `target + at most one row`; the manifest
records the exact bytes and row count.

For a quick check:

```bash
.venv/bin/python benchmarks/alternatives/feature_store/generate_features.py \
  --rows 1000 \
  --output benchmarks/alternatives/data/smoke.jsonl \
  --force
```

## Output

- JSONL: one learner feature row per line.
- Sidecar manifest: `<output>.manifest.json` with schema version, seed,
  target bytes, actual bytes, row count, elapsed time and generation rate.
- `benchmarks/alternatives/data/` is gitignored; do not commit multi-GB files.

## Schema

The row mirrors the online feature-store payload:

```json
{
  "learner_pseudonym": "k1_000000000000000000000000",
  "completion_rate_30d": 0.6394,
  "avg_pass_rate_30d": 0.025,
  "active_days_30d": 8,
  "preferred_platform": "web",
  "skill_mastery": {"general": 0.2232, "sql": 0.7365, "python": 0.6767},
  "computed_at": "2026-11-10T00:00:00",
  "session": {
    "events_in_session": 69,
    "active_minutes": 7.82,
    "last_verbs": ["play", "play", "play"],
    "current_course_id": "c-py-201"
  }
}
```

Keys are unique (`k1_<zero-padded row index>`) and deterministic for a given
seed, so Redis and ScyllaDB loaders can replay the same workload.

## Notes

- 5 GiB at the current row size is roughly 14 million rows.
- Generation is CPU/disk-bound; do not write the file inside a git-tracked path.
- For the memory-pressure experiment, cap Redis (`maxmemory 512mb`) and compare
  hit/eviction/latency against ScyllaDB rather than trying to exhaust host RAM.

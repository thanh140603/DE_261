# BR4 / BR5 contracts

`v1/*.schema.json` are generated from the executed Pydantic contracts:

```bash
python -m edu_platform.br45.export_contracts
```

The independent `br45-postgres-cdc` connector preserves Debezium's `before`,
`after`, `op`, `source.lsn`, `source.txId` and source transaction timestamps.
It accepts both schema-wrapped and schema-free envelopes. It does not use the
older public-LMS connector's unwrap transform.

Source row primary keys are `id`, or `(id, version)` for questions and test cases.
Deletes retain tombstones in `analytics.clean_rows`; the raw log retains the
original envelope. Debezium transaction time measures capture latency; learning
`event_time` drives Spark windows. All analytical timestamps use UTC.

Normalized activity deltas use a stable mutation identity. Updates emit `-1`
for the prior event and `+1` for its replacement; deletes emit `-1`. Clock and
metadata refresh events carry zero weight. Kafka tombstones carry no activity.
The outbox and Spark deduplication preserve identities across retries.

Null deadlines impose no deadline penalty. Missing activity is unknown until
there is an actual observation; it is not inferred from a missing telemetry row.
Missing/skipped/invalid required evaluations invalidate question attempts.
Question and test-case versions are separate analytical dimensions.

See `docs/BR4_BR5_IMPLEMENTATION.md` for denominators, eligibility, watermark,
retention, replay, late-data and schema migration rules.

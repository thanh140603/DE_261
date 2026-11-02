# ADR 0014: Spark Structured Streaming for the telemetry fast path and BR7/BR8 live overlays

Status: accepted - 2026-11-02 (supersedes ADR 0004 for these jobs; follows ADR 0009's choice
for BR5; keeps ADR 0011: no streaming job writes Delta)

## Context
ADR 0004 assigned the low-latency telemetry normalisation and the BR7/BR8 live overlays to
Flink. None of those Flink jobs existed (`flink_env.py` was a stub), while Spark Structured
Streaming already runs the lakehouse landing and BR5 in this repository, and the Spark
normaliser already wraps the domain `NormalizeEvents` use case.

## Decision
One Spark app (`edu stream telemetry-live`, compose service `telemetry-live`) runs three
checkpointed queries:
- **normalise**: `telemetry.events.raw.v1` -> the same `normalize_rows` as silver (validate,
  migrate schema, pseudonymise, drop client PII, flag lateness, correct clock skew) ->
  `telemetry.learning_events.v1`, rejects -> `telemetry.events.dlq.v1` (`rejected_by:
  spark-stream`). One Kafka write per micro-batch, routed by a `topic` column.
- **BR7 heatmap / BR8 engagement**: learning events, event-time watermark 5 min
  (`LatenessPolicy`), `dropDuplicatesWithinWatermark(event_id)`, per UTC day aggregation ->
  Redis hashes with **absolute** values (replays rewrite, never add). Engagement uses the
  domain's `verb_weights`, the same as `gold.fct_learner_daily_activity`.
- The API serves the marts and adds a `live` block only for days after the mart snapshot
  (heatmap: newest version only); Redis failures degrade to mart-only responses.
- `ClockSkewPolicy` (domain): events dated > 2 min after ingestion are pinned to ingestion
  time, so a client clock running ahead cannot advance every watermark.

## Consequences
- One engine for all streaming in this repository; Flink services remain in compose but run
  no jobs. The PDF names Flink: this deviation is deliberate and recorded here.
- Measured on the local stack (Colima, 6 CPU): event published -> visible in the API,
  median 6.8 s, max 9.5 s (normalise micro-batch ~2.7 s; 1 s triggers). Good enough for an
  overlay on daily marts; sub-second would need Flink or a non-JVM consumer.
- Events later than the watermark only reach the marts (by design, documented in the UI).
- Live events carry no content version: on the day a video is re-cut, the overlay mixes
  both versions; it is only shown on the newest version.

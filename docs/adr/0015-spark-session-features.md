# ADR 0015: Session features on Spark Structured Streaming with Redis state

Status: accepted - 2026-11-11 (refines ADR 0011 and ADR 0014)

## Context
BR2 needs a streaming session branch (30-minute inactivity gap) with a 30-second
freshness target. The original plan assigned it to Flink keyed state (ADR 0004/0011),
but the platform's live telemetry path is already Spark Structured Streaming
(ADR 0014) and the Flink environment factory is still a TODO.

Spark 3.5 rejects `update` output mode for `session_window` on streaming
DataFrames. With `append` output, a session is emitted only when the watermark
passes the 30-minute gap, so the online feature would be ~30+ minutes stale -
unacceptable for the BR2 serving path.

## Decision
- Session features run as a Spark Structured Streaming `foreachBatch` job
  (`edu stream session-features`, also started by `telemetry-live`).
- The small per-learner session state lives in Redis, not in Spark state:
  `edu:features:session:<pseudonym>` is an absolute snapshot.
- Every event id is claimed with `SET NX` for one hour, so an at-least-once
  Kafka replay cannot double-count events.
- A session id change or a gap longer than 30 minutes starts a new session.
- The job publishes `features.session.v1` for landing/audit and writes the
  Redis document for serving.
- Flink remains the intended engine for the low-latency normalisation fast path
  once its adapter is implemented; this ADR only moves the session branch.

## Consequences
- One streaming engine for the currently running live path (Spark), no second
  runtime to operate for BR2.
- Session state is external (Redis); the checkpoint protects Kafka offsets, and
  the event-id claim makes replays idempotent.
- The 30-second freshness comes from the micro-batch trigger, not from a
  watermark, so a session is visible while it is still open.
- If Flink 2.x + a stable Delta/Kafka connector become available, the domain
  policy (`SessionFeaturePolicy`) and the `features.session.v1` contract can be
  reused by a Flink job without changing the API.

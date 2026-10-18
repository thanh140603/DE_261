# ADR 0012: Gold layer = Kimball star schema with deterministic surrogate keys

Status: accepted - 2026-10-18

## Context
Eight requirements read overlapping facts (events, submissions, enrollments, risk) by the same
entities (learner, course, content, assignment, organisation). Without conformed dimensions each
mart re-derives them and drifts. The lakehouse also has no sequence service, rebuilds tables
often (idempotent jobs, backfills) and receives facts before dimensions (telemetry outruns CDC).

## Decision
- Gold is a **dimensional model**: conformed `dim_*` + `fct_*` with a declared grain;
  BR marts are built from gold only.
- **Surrogate keys are deterministic**: `xxhash64(natural key)` for SCD1,
  `xxhash64(natural key, valid_from)` for SCD2. Rebuilds reproduce keys; facts and dims
  build independently; no identity columns.
- **SCD2** where history changes answers: `dim_learner` (organisation/advisor - B2B reports
  attribute activity to the org at the time) and `dim_content` (per version - a re-cut video
  shifts its seconds, BR7). Everything else SCD1.
- **Late-arriving dimensions** get an *inferred member* with the key the real row will have
  (first SCD2 version starts 1900-01-01); the real row overwrites it in place, so facts never
  need re-keying. Key `-1` = not applicable / unknown.
- Thresholds used by marts come from the domain value objects, injected as SQL parameters, and
  unit tests keep the warehouse vocabulary in sync with the domain.

## Consequences
- 64-bit hash collisions are theoretically possible; at the expected cardinality (millions of
  natural keys) the probability is negligible and the orphan-key quality gate would surface it.
- Snapshot-based SCD2 (`dim_learner`) records changes at silver cadence (minutes in streaming,
  hourly in batch); intermediate states inside one batch are not versioned.

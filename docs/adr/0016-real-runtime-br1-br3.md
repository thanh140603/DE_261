# ADR 0016: Real runtime for BR1–BR3 — service mode plus the BR2 feature store

Status: accepted — 2026-11-12 (supersedes the "production entrypoints are TODO
stubs" consequence of ADR 0008 for BR1–BR3)

## Context

ADR 0008 introduced an in-process demo runtime behind the same ports, so the
whole platform could be demonstrated on a laptop without Kafka, Redis and
PostgreSQL. That decision deliberately left the Kafka/Redis adapters for the
notification and grading contexts as TODO stubs. As a result, BR1–BR3 were
correct in the domain but did not exercise the real delivery path: the UI read
an in-memory inbox, grading ran in the API process, and BR2 had only the batch
feature branch.

The platform now runs Kafka, Redis and PostgreSQL in the same Compose project,
and the grading/notification use cases already sit behind ports. The remaining
gap is an entrypoint decision, not domain logic.

## Decision

- Keep `EDU_BR13_MODE=demo` as the default for UI-only work. It needs no
  infrastructure and remains the fastest way to inspect screens.
- Add `EDU_BR13_MODE=service` and the `docker-compose.br13.yml` overlay:
  - `notification` consumes the five notification topics, resolves audiences
    from PostgreSQL, persists to Redis, uses SMTP and webhook senders, and
    publishes `notification.dispatched.v1` / `notification.suppressed.v1`.
  - `grading-ingest` owns the HTTP 202 boundary and publishes
    `grading.submission_received.v1` only after the broker acknowledges;
    `grading-worker` claims each submission with `SET NX`; `grading-normalizer`
    persists to `grading.*` and publishes `grading.submission_graded.v1`.
  - The API reads Redis notifications and proxies grading calls to
    `grading-ingest`; a Kafka-to-SSE bridge forwards `notification` and
    `submission.graded` events to the browser.
- Keep `public.*` as the LMS schema. `grading-projector` copies `grading.*` into
  `public.*` only when the `br13-project` profile is enabled, so BR4–BR8 keep
  their baseline by default.
- Run the BR2 batch branch as `edu batch features-online` (Delta →
  `edu:features:longterm:*`) and the session branch as
  `edu stream session-features` / `telemetry-live` (Redis session state →
  `features.session.v1`), per ADR 0015.

## Consequences

- BR1–BR3 now run end to end on the real event bus and stores; the demo runtime
  remains a supported mode with the same domain code.
- The stack needs Kafka, Redis and PostgreSQL for the service path, and the
  sandbox is still a local subprocess/SQLite (not a security boundary).
- The `grading` schema is owned by BR3. Enabling the projector is an explicit
  integration step that may change BR4/BR6 history and BR2 features, so those
  baselines must be rebuilt when it is on.
- SMTP and push use local Mailpit/push-sink in evidence runs. Production
  provider credentials are configuration, not code.

# What was implemented for BR4 and BR5

Implemented and evaluated on 16 October 2026. This document describes the code
delivered in this change, its executed checks, and how to reproduce the results.
All demonstration and benchmark records are explicitly synthetic.

## 1. What changed

The repository already had a FastAPI/React demo and Docker services for
PostgreSQL, Debezium, Kafka, Redis, Spark and Flink. Its BR4/BR5 application
results lived in Python memory; their deployment jobs were unimplemented.

| Area | Previous behavior | Delivered behavior |
|---|---|---|
| BR4 ingestion | In-memory sandbox records | Actual PostgreSQL rows captured through WAL, Debezium and Kafka |
| BR4 processing | Assignment-item demo aggregation | SQL question/test-version aggregation, valid-attempt semantics, retry metrics and explainable rules |
| BR4 storage | Recomputed Python objects | Persistent question, test-case and anomaly marts in PostgreSQL |
| BR5 ingestion | Simulator-created CDC-like dictionaries | Separate working Debezium PostgreSQL connector, snapshot/insert/update/delete handling |
| BR5 processing | In-process signal scoring | Spark Structured Streaming with real event-time hopping windows, watermarks and checkpoints |
| BR5 outputs | In-memory scores and alert list | Persistent window counts, risk states, history and intervention alerts |
| Application | Unscoped demo views | Token-authenticated, course-scoped Instructor and Advisor APIs and dashboards |
| Evidence | Domain tests | SQL/Python parity, database/API tests, genuine CDC/Spark workflow, browser tests and measured benchmarks |

Existing learner notifications, recommendations, grading, video analytics,
content synchronization and organization reports retain their original demo
behavior. Existing public LMS tables and the original Debezium connector were
preserved. The user's pre-existing MinIO, README and Compose changes were not
replaced.

## 2. Requirements traceability

| Requirement | BR4 | BR5 |
|---|---|---|
| Stakeholder and goal | Instructor: find assessments requiring review | Advisor: identify learners who may need intervention |
| Inputs | Courses, assignments, versioned questions/tests, submissions and evaluations | Enrollments, actual activity, due assignments, submissions and evaluation clock |
| Operational storage | `br45.*` PostgreSQL tables | Same operational schema |
| Ingestion | PostgreSQL WAL → Debezium → Kafka → raw/clean landing | Same CDC path; signed activity outbox feeds Spark |
| Processing | `assessment.py`: SQL aggregation and configurable anomaly policy | `streaming.py`: Spark windows; `risk.py`: explainable scoring and alert transitions |
| Persistent outputs | `mart_question_pass_statistics`, `mart_test_case_pass_statistics`, `mart_question_anomalies` | `activity_windows`, `risk_state`, `risk_history`, `dropout_alerts` |
| APIs | Instructor course/question/test-case/anomaly endpoints | Advisor risk/history/alert endpoints and acknowledgement/resolution |
| UI | Instructor → Assessment health | Advisor → Learners to review, Intervention alerts, Risk detail |
| Acceptance evidence | Deterministic SQL/Python agreement, corrected grades reaching browser | Actual WAL changes, replay, updates/deletes, checkpoint restart and learner recovery reaching browser |
| Performance evidence | `evidence/br45/br4_benchmark.csv` | `evidence/br45/br5_stream_benchmark.csv`, `e2e_result.json` |

## 3. Architecture and dependencies

```text
                        PostgreSQL operational schema: br45
                 metadata / enrollment / submissions / activity
                                      |
                         WAL logical replication (pgoutput)
                                      |
                    Debezium connector: br45-postgres-cdc
                                      |
                      Kafka: br45.cdc.br45.<table>
                                      |
                         Transactional CDC landing worker
                    raw_changes -> validated clean_rows
                            /                       \
                   SQL aggregation            durable signed outbox
                         |                           |
                  BR4 persistent marts        Kafka: br45.activity.v1
                         |                           |
                  Instructor APIs             Spark event-time windows
                         |                           |
                  Instructor view             activity_windows
                                                     |
                                           risk / history / alerts
                                                     |
                                               Advisor APIs
                                                     |
                                               Advisor view
```

PostgreSQL is both the operational database and the analytical serving database,
with separate schemas. Kafka and Debezium reuse existing infrastructure. Spark
3.5.1 performs genuine streaming window processing. SQL performs BR4 relational
processing. No new database, paid service, GPU or frontend framework was added.

The operational tables are additive because the unused public LMS schema lacked
questions, test versions and meaningful activity and used UUIDs incompatible
with the application's string reference identifiers. The new schema uses those
reference course identifiers without changing public tables. Existing public
records are **not automatically imported or reinterpreted**.

The executable BR5 choice is recorded in
[ADR 0009](adr/0009-persistent-br4-br5-runtime.md), which supersedes ADR 0004's
Flink-only decision for BR5. Other BRs retain their existing engine choices.
The Spark driver runs locally with two threads inside a container; it does not
require the separate Spark master/worker services. Its image uses Python 3.11
and Java 17 because the original Spark image bundles Python 3.8.

## 4. Files and implemented responsibilities

| File | What it implements |
|---|---|
| `infra/postgres/br45.sql` | Repeatable additive migration, operational constraints, analytical tables and indexes |
| `infra/debezium/br45-connector.json` | Independent pgoutput connector retaining complete Debezium envelopes |
| `infra/br45/Dockerfile`, `stream.py` | Compatible Spark driver and pinned Kafka connector dependencies |
| `docker-compose.yml` | Opt-in `br45` profile, migration/connector initializer, CDC worker, Spark worker, persistent checkpoints, shared policy environment |
| `br45/config.py` | Validated environment configuration and coherent window/risk thresholds |
| `br45/contracts.py`, `outputs.py` | Executed source and API data contracts |
| `br45/db.py` | PostgreSQL transactions, migrations and durable pipeline state |
| `br45/cdc.py` | Raw ingestion, validation/quarantine, stable deduplication, LSN ordering, updates/deletes, outbox publication and clocks |
| `br45/assessment.py` | SQL marts, independent Python aggregation, first/latest attempts, version manifests and anomaly reasons |
| `br45/streaming.py` | Kafka source, watermark, bounded event-id deduplication, hopping aggregation, checkpointing and absolute window upserts |
| `br45/risk.py` | Exact feature eligibility, point scoring, auditable history, cooldown and alert lifecycle |
| `br45/api.py` | Instructor/advisor authorization, filters, pagination, analytical APIs and genuine learner activity write path |
| `br45/fixtures.py`, `cli.py` | Deterministic synthetic seed, safe source reset, controlled clock, recovery and operational commands |
| `br45/benchmark.py`, `stream_benchmark.py` | Reproducible measured comparisons and CSV/chart generation |
| `br45/verify.py` | Actual PostgreSQL-to-API acceptance workflow, including replay and optional Spark restart |
| `br45/export_contracts.py`, `schemas/br45/v1` | Regenerable JSON Schema contracts |
| Existing `entrypoints/batch/assessment_mart_job.py` | Working dated BR4 mart refresh, replacing its stub |
| Existing `entrypoints/streaming/dropout_risk_job.py` | Working delegate to the BR5 Spark job, replacing its stub |
| `apps/web/src/analytics.ts` | Typed authenticated analytical API client |
| `AnalyticsAccess.tsx`, `AssessmentHealth.tsx` | Staff access, polling, pagination and question/test-case exploration |
| `InstructorView.tsx`, `AdvisorView.tsx` | Integrated persistent dashboards, explanations, filters, risk history and alert actions |
| `tests/unit/test_br45.py` | Deterministic policy, denominator, eligibility and contract checks |
| `tests/integration/test_br45.py` | PostgreSQL aggregation, CDC semantics, authorization and alert lifecycle checks |
| `tests/e2e/test_br45.py`, `apps/web/tests/br45.spec.ts` | Full pipeline and real browser acceptance workflows |

Paths abbreviated as `br45/` above are under `src/edu_platform/br45/`.

## 5. Source contracts and data management

The migration creates courses, assignments, questions, test cases, enrollments,
submissions, evaluations, activity events and clocks. Operational foreign keys
protect assessment relationships. Evaluations are unique on
`(submission_id, test_case_id, test_case_version)`. Questions and test cases use
`(id, version)` primary keys. Submissions and activities use stable `id` values.
UTC is used for storage and processing; the browser formats timestamps locally.
Date filters explicitly use UTC and half-open intervals.

Each accepted change retains its original envelope in `analytics.raw_changes`.
Raw transport identity is `(topic, partition, offset)`. A second stable identity
includes table, WAL LSN, transaction id, operation and row image, suppressing
semantically repeated CDC records at new Kafka offsets. Clean rows are keyed by
table/row identifier, track the last LSN, and retain deleted tombstones. Older
LSNs cannot resurrect newer records. Invalid contracts enter `quarantine` with
their reason and original payload.

The new connector supports initial snapshot operation `r`, inserts `c`, updates
`u`, deletes `d`, schema-wrapped envelopes, and Kafka tombstones. Relevant tables
use `REPLICA IDENTITY FULL`. Learning activity time comes from `event_time`;
Debezium transaction/processing timestamps remain capture metadata.

Source rows and the signed-event outbox commit before publication. Publication
is retried from durable pending rows. A crash after Kafka delivery but before
marking an outbox row published can duplicate its message; its stable event id
lets Spark remove that replay. CDC consumer offsets commit after database work.

Analytical tables have primary keys and course/window/history indexes. JSONB
join indexes support relational aggregation. This local workload uses indexed
tables rather than claiming unnecessary partitioning. Raw logs, history and
materializations currently have no automatic retention deletion; Spark's
watermarked processing state is bounded.

## 6. BR4 metric semantics and detection

All observation intervals are `[start, end)`. Required test versions are the
latest versions existing **at submission time**, within the submission's exact
question version. Optional tests do not determine question completion. A later
test revision does not silently reinterpret an earlier submission.

An individual test evaluation is valid only when the submission is evaluated,
the evaluation is explicitly valid, its status is `passed`, `failed`, `error`
or `timeout`, and its evaluation time precedes the observation end. Learner-code
errors/timeouts are academic failures. `infra_error`, pending, missing, skipped
and invalid results do not enter academic pass-rate denominators.

A question attempt is valid only when every required test in that manifest has
a valid evaluation. It passes only when every required test passes. A missing
required test invalidates the whole question attempt; independently valid tests
can still contribute to their own test-case statistics. Invalid attempts and
infrastructure errors are reported separately.

```text
pass_rate = passed valid evaluations / total valid evaluations
```

Question rates count valid submission attempts, so retries contribute additional
attempts. Unique-student counts drive the sample-size guard. First/latest rates
use each student's first/latest **valid evaluated attempt within the selected
window and question version**, ordered by submission timestamp then stable id.
A zero denominator returns `null`, displayed as an unavailable rate.

Default rules are configurable:

| Rule | Default |
|---|---:|
| Minimum distinct valid students | 20 |
| Question low pass rate | Below 30% |
| Test-case low pass rate | Below 20% |
| Suspicious test gap from other comparable required tests' median | At least 50 percentage points |
| Decrease against preceding equal-duration window | At least 30 percentage points |

The five states are `NORMAL`, `INSUFFICIENT_DATA`, `LOW_PASS_RATE`,
`SUSPICIOUS_TEST_CASE` and `NEEDS_REVIEW`. Peer and previous-window comparisons
also require adequate supporting samples. Results retain identifiers, versions,
window bounds, counts, reasons and thresholds. A flag requests instructor
inspection; it does not establish that an assessment is defective.

CDC changes refresh the default 30-day materialization. APIs can materialize
other date ranges from the same clean facts. Stable keys replace absolute totals
rather than incrementing counters. Cached windows are invalidated by the last
accepted assessment-source revision. Corrections and deletions therefore change
the results without manually editing files or rerunning a seed.

## 7. BR5 streaming, features and scoring

Spark reads `br45.activity.v1`, parses event timestamps, applies a 21-day default
watermark and `dropDuplicatesWithinWatermark(event_id)`, and aggregates signed
counts with `window(event_time, '7 days', slide)`. The default slide is one hour;
the trigger checks for Kafka input every five seconds. This is an actual
Structured Streaming stateful window aggregation, not a scheduled SQL query.

For a UTC-aligned evaluation boundary `T`, the feature windows are:

```text
recent:       [T - 7 days,  T)
previous:     [T - 14 days, T - 7 days)
14-day count: recent + previous
```

Activity updates retract the prior event's window contributions and add its
replacement. Deletes retract prior contributions. Zero-weight clock events
create empty windows and advance inactivity even when learners do nothing.
`wall` mode emits clock boundaries automatically; `manual` mode consumes the
controlled clock written to PostgreSQL. No learning behavior is invented by a
clock event.

Risk is evaluated at the latest completed boundary. An activity in the current
open hour influences the next hourly evaluation. The supported slide must divide
seven days exactly. Within-watermark out-of-order changes are accepted. An
activity mutation whose old or new timestamp is at/before the persisted Spark
watermark is quarantined for controlled backfill. Source history remains in the
raw log; silently changing already-evicted window state is avoided.

Every micro-batch transaction upserts absolute window totals. Spark uses a
persistent checkpoint volume. Risk scoring waits until committed Spark source
offsets cover all published outbox offsets and no outbox rows remain pending;
partial features do not create premature alerts.

Eligibility requires active enrollment for at least seven days. Activity and
submissions must occur at/after enrollment and before evaluation. Due required
assignments must have deadlines within the last 14 days, at/after enrollment,
and have been published by their deadline. Future deadlines impose no penalty.

The assignment feature is a **submission rate**, not a calibrated completion or
mastery estimate. Any non-infrastructure submission before evaluation satisfies
that due assignment; late submissions can clear an outstanding missed deadline.
When no required assignments are due, the denominator is absent and that signal
is disabled. Missing telemetry alone is not definite inactivity: the inactivity
signal requires a real prior activity observation and configured telemetry.

| Applicable signal | Points |
|---|---:|
| At least seven days since observed meaningful activity | 35 |
| At least one due required assignment remains unsubmitted | 30 |
| Due-assignment submission rate below 50% | 20 |
| Activity falls at least 50%, with at least 3 previous-window observations | 15 |

The score is capped at 100. Levels are LOW 0–29, MEDIUM 30–59, HIGH 60–79 and
CRITICAL 80–100. Points, level boundaries, alert threshold and cooldown can be
configured. Every result includes features, explanations, eligibility,
evaluation timestamp and policy. Scores are **not dropout probabilities**.

One open alert is allowed per student/course. Crossing 60 points generates an
alert; the default cooldown is 72 evaluation hours. Existing open alerts update
with current severity/reasons. Repeated high scores do not generate endless
alerts. Acknowledgement/resolution retain timestamps and actor identifiers;
recovering below threshold automatically resolves an open alert. A manually
resolved alert does not reopen while risk merely remains high. A later eligible
transition or significant worsening can alert after cooldown. Deleted enrollment
or course records retire current risk and resolve open alerts. Risk observations
and corrections remain in auditable history.

## 8. APIs and user interface

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.
Machine-readable source/output contracts are under `schemas/br45/v1/`.

| Method | Endpoint |
|---|---|
| GET | `/api/instructor/courses/{course_id}/questions/statistics` |
| GET | `/api/instructor/questions/{question_id}/statistics` |
| GET | `/api/instructor/questions/{question_id}/test-cases` |
| GET | `/api/instructor/courses/{course_id}/anomalies` |
| GET | `/api/instructor/anomalies/{anomaly_id}` |
| GET | `/api/advisor/courses/{course_id}/at-risk-students` |
| GET | `/api/advisor/students/{student_id}/risk` |
| GET | `/api/advisor/students/{student_id}/risk-history` |
| GET | `/api/advisor/alerts` |
| PATCH | `/api/advisor/alerts/{alert_id}/acknowledge` |
| PATCH | `/api/advisor/alerts/{alert_id}/resolve` |
| GET | `/api/analytics/session`, `/api/analytics/diagnostics` |
| POST | `/api/learning/activity` |

Lists use `{items, total, offset, limit}`; limit is 1–100. Instructor filters
include course, assignment, UTC dates, state and severity, with stable selectable
sorting. Advisor endpoints filter by authorized course, risk level, UTC dates
and alert status where relevant. Missing/incorrect tokens return 401, incorrect
roles or explicit out-of-scope courses return 403, unavailable scoped students
return 404, invalid queries return 422 and unavailable storage returns 503.

`EDU_BR45_AUTH` is a server-configured JSON mapping of bearer tokens to identity,
role and explicit course scopes. Client-supplied role/course claims are not
trusted. Learner activity writes derive student identity from the token and
require active enrollment. Tokens are entered in the view and stored only in
the tab's session storage. The existing application had no shared identity
provider; this is a deliberately small course-scoped local authentication layer.

Compose provides public **local demonstration** identities when no token mapping
is configured: `instructor-demo`, `advisor-demo`, and `learner-demo`. The advisor
and learner identities are restricted to `c-py-201`. Configure private tokens
for a shared deployment. Authentication applies to the new persistent BR4/BR5
paths; unrelated pre-existing demo endpoints retain their previous behavior.

The Instructor dashboard shows question/test versions, valid attempts, distinct
students, first/latest rates, invalid/infrastructure counts and review reasons.
Selecting a question opens its required test-case breakdown. The Advisor view
shows monitored active enrollments, risk-level counts, learner features, risk
history, alerts and acknowledgement/resolution controls. Both handle loading,
empty and error states and poll actual API data every five seconds.

The shared shell's pipeline strip and live-event drawer still describe the
other in-memory demo pipelines. Its alert tile is labeled **Demo alerts**;
persistent BR5 alerts are the Advisor table and API, not that legacy counter.

## 9. Executed correctness and business evidence

The delivered checks include:

- 184 passing unit tests across the repository, including the new BR4/BR5 cases.
- 13 passing PostgreSQL/API integration tests covering SQL/Python parity,
  first/latest attempts, all-pass/all-fail behavior, missing/invalid evaluations,
  infrastructure versus code errors, version changes, distinct-student guards,
  duplicates, old LSNs, late-event quarantine, authorization and alert lifecycle.
- A real PostgreSQL → WAL → Debezium → Kafka → Spark → API workflow with six
  acceptance checks, including source grade correction, explicit Kafka replay,
  activity UPDATE/DELETE retractions and checkpoint restart/recovery.
- The final container-based automated E2E test also passed (`1 passed`),
  including another actual Spark checkpoint restart. Its independent result is
  [saved here](evidence/br45/final_e2e_result.json).
- Browser workflows for instructor drill-down and corrected-grade refresh,
  advisor acknowledgement/recovery, access errors, and desktop/mobile layout.
- Repository Ruff checks, formatting, mypy and the frontend production build.

The primary fixture has 24 distinct evaluated students and three required test
cases. Two pass all tests; the other 22 fail one test. The question rate is
`2/24 = 8.3333%`. Two tests have `24/24 = 100%`; the problematic test has
`2/24 = 8.3333%` and a 91.6667 percentage-point gap from its peers. Correcting one
failed evaluation increases the question's pass count from 2 to 3. The browser
test observed its displayed rate change from 8% to 13% without page reload.

The risk fixture has four previous-week activities, no recent activity and an
unsubmitted due assignment, producing 100 points. Four real activity writes
through the learner endpoint remove inactivity/decline signals, reducing risk
to 50 and resolving the alert. A new enrollment scores zero. These are verified
synthetic scenarios, not labeled real dropout outcomes.

See [end-to-end evidence](evidence/br45/e2e_result.json) and
[browser results](evidence/br45/browser-results.json). Screenshots:
[Instructor desktop](evidence/br45/instructor-desktop.png),
[Instructor mobile](evidence/br45/instructor-mobile.png),
[Advisor desktop](evidence/br45/advisor-desktop.png),
[Advisor mobile](evidence/br45/advisor-mobile.png).

## 10. Measured performance and alternatives

Benchmarks ran on Linux x86-64 with 6 logical CPUs and approximately 18.4 GiB
RAM while the local stack was running. Host benchmark Python was 3.12.3;
PostgreSQL was 16.15. The Spark service uses Spark 3.5.1, Python 3.11, Java 17
and `local[2]` with a 1 GiB driver. Each scale was measured three times.
[Environment details](evidence/br45/environment.json) and raw CSVs retain the
unrounded measurements. Results are local observations, not capacity guarantees.

### BR4

Both alternatives use identical validated joined facts and metric semantics.
The Python timing includes fetching those facts and aggregating them. The SQL
timing includes separate question and test aggregation queries. Persisted refresh
also writes marts and evaluates anomalies. A single-record correction refreshes
the affected materialization rather than an unsafe counter increment.

| Evaluation rows | SQL aggregation mean | Python baseline mean | Persisted refresh mean | Mart query mean | Correction refresh mean |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 36.70 ms | 22.08 ms | 44.61 ms | 0.39 ms | 43.67 ms |
| 10,000 | 400.10 ms | 197.81 ms | 410.35 ms | 0.48 ms | 409.71 ms |
| 100,000 | 3,934.70 ms | 1,953.97 ms | 3,996.46 ms | 0.39 ms | 3,984.81 ms |

SQL and Python matched at every scale/repetition. Python was faster here because
it reuses joined facts across both aggregates; the SQL implementation repeats
some JSONB joins. SQL was retained for persistent, transactional serving and
clear database semantics. This result supports future typed fact tables or
shared SQL intermediate results instead of claiming SQL won the benchmark.

![Measured BR4 comparison](evidence/br45/br4_benchmark.svg)

Raw results: [BR4 CSV](evidence/br45/br4_benchmark.csv).

### BR5

The real CDC acceptance run measured approximately **10,163.83 ms from source
writes to the persisted risk/alert result**, and **20,142.00 ms from restarting
Spark to persisted recovery**. It generated zero duplicate alerts after replay.
These are individual workflow measurements, not latency percentiles.

The scale experiment isolates **normalized Kafka → Spark → PostgreSQL windows**.
It publishes explicitly synthetic normalized messages directly to Kafka,
including about 1% duplicate identities and clock records. It does **not** claim
to measure CDC throughput or full source-to-alert latency at those scales.
Results are checked against an independent periodic-batch-style Python interval
aggregation with identical deduplication and time boundaries.

| Unique events | Kafka-to-persisted-window mean | Mean observed unique events/s | Python batch compute mean |
|---:|---:|---:|---:|
| 1,000 | 6,456.27 ms | 167.05 | 4.42 ms |
| 10,000 | 8,215.95 ms | 1,332.22 | 29.02 ms |
| 100,000 | 14,847.64 ms | 6,742.26 | 296.77 ms |

All nine stream/batch comparisons matched their recent/previous window counts.
Batch computation is much cheaper for a single static snapshot. Streaming adds
continuous ingestion, correction/replay handling, checkpoints and automatic
persistent updates; it also incurs micro-batch scheduling and sink costs. A
periodic batch deployment would additionally wait for its schedule before
noticing changes. No empirical false-positive/negative or calibrated prediction
claims are made because reliable real dropout labels were unavailable.

Raw results: [BR5 CSV](evidence/br45/br5_stream_benchmark.csv).

## 11. Demonstration runbook

Run these commands from the repository root. The first image build downloads
dependencies; subsequent source builds reuse dependency layers.

### Start the required services

```bash
docker compose --profile br45 up -d --build demo br45-init br45-cdc br45-stream
docker compose --profile br45 ps
docker compose --profile br45 logs --tail=50 br45-init br45-cdc br45-stream
```

The initializer applies the migration, creates Kafka topics and idempotently
registers the separate connector. It exits successfully; this is expected.
The command starts the existing PostgreSQL/Kafka/Redis/Connect dependencies.
Flink, MinIO and separate Spark cluster services are not required for this path.

### Load the demonstration and inspect BR4

```bash
docker compose exec -T br45-cdc python -m edu_platform.br45.cli seed
docker compose exec -T br45-cdc python -m edu_platform.br45.cli br4
```

Open `http://localhost:8000/instructor`, enter `instructor-demo`, and click
Connect. Choose Python for Data in **Assessment course**, then select the
synthetic sum-even question. Verify 24 valid attempts, two passes, 24 students
and the suspicious test's explicit review reason. The separate outer Course
selector continues to control the other instructors' video/content demo panels.

```bash
curl -s -H 'Authorization: Bearer instructor-demo' \
  http://localhost:8000/api/instructor/courses/c-py-201/questions/statistics
```

### Inspect BR5 and demonstrate recovery

Open `http://localhost:8000/advisor`, enter `advisor-demo`, and click Connect.
Inspect `br45-demo-at-risk`, its four explanations and its intervention alert.
Acknowledge the alert, then run:

```bash
docker compose exec -T br45-cdc python -m edu_platform.br45.cli recover
```

After CDC/Spark processing and the next browser poll, its recent activity count
becomes four, score becomes 50, and the open alert resolves. Select the learner
to inspect the persisted risk trend. No local UI score calculation is used.

```bash
curl -s -H 'Authorization: Bearer advisor-demo' \
  http://localhost:8000/api/advisor/students/br45-demo-at-risk/risk
curl -s -H 'Authorization: Bearer advisor-demo' \
  http://localhost:8000/api/analytics/diagnostics
curl -s http://localhost:8083/connectors/br45-postgres-cdc/status
```

### Controlled time

For deterministic clock demonstrations, start the profile with
`EDU_BR45_CLOCK_MODE=manual`. Seed once and advance the clock monotonically:

```bash
# Choose an actual boundary later than the current stored evaluation clock.
docker compose exec -T br45-cdc python -m edu_platform.br45.cli clock \
  --at 2026-10-17T15:00:00Z
```

That command writes PostgreSQL; its clock change travels through CDC. A fixed
example date is not required for normal operation. Do not move the clock
backward. After an accelerated demo, retain manual mode or use an isolated demo
database/checkpoint for a fresh time origin.

### Install local verification tools

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[demo,dev]'
cd apps/web && npm ci && npx playwright install chromium && cd ../..
```

Python must be 3.11 or newer. On Windows use the virtualenv's `Scripts` directory.

### Run correctness and integration checks

```bash
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy
.venv/bin/python -m pytest tests/unit

# First use only: create a separate disposable integration-test database.
docker compose exec -T postgres createdb -U lms br45_test
EDU_BR45_TEST_DSN=postgresql://lms:lms@localhost:5433/br45_test \
  .venv/bin/python -m pytest tests/integration/test_br45.py

# Requires the running profile and the 24-student seed.
.venv/bin/python -m edu_platform.br45.verify --restart
EDU_BR45_E2E=1 .venv/bin/python -m pytest tests/e2e/test_br45.py

# Re-seed before this browser workflow; it deliberately demonstrates recovery.
docker compose exec -T br45-cdc python -m edu_platform.br45.cli seed
cd apps/web && npm run build && npm run test:br45 && cd ../..
```

Integration tests skip unless their test DSN is supplied and roll back their
analytical changes. The real workflow creates uniquely named synthetic learners,
retains analytical evidence, and removes their operational rows after success.
Browser screenshots/results are written under `docs/evidence/br45/`.

### Run measured experiments and export contracts

```bash
.venv/bin/python -m edu_platform.br45.cli benchmark
.venv/bin/python -m edu_platform.br45.stream_benchmark
.venv/bin/python -m edu_platform.br45.export_contracts
```

BR4 benchmark changes roll back. BR5 stage benchmarks leave labeled synthetic
window records and Kafka messages so checkpoint/replay behavior stays coherent.
They do not create enrolled learners or advisor alerts.

### Safe reset and stop

```bash
# Only br45-demo-* operational rows; keeps shared courses and analytical audit.
docker compose exec -T br45-cdc python -m edu_platform.br45.cli reset-demo
docker compose exec -T br45-cdc python -m edu_platform.br45.cli seed

# Stop without deleting containers, broker state, database or checkpoints.
docker compose --profile br45 stop
```

Re-seeding uses stable ids and is not an alert-history wipe. Existing resolved
alerts and the cooldown deliberately suppress repeated fixture warnings. Use
`verify --restart` for a repeatable new-alert demonstration with a fresh student.
Use `up -d` with the same profile/services to resume. The existing Kafka service
uses Docker-managed anonymous data volumes; `stop` preserves its container and
volume association. Removing/recreating broker state requires coordinated backup
and restore with database and checkpoints; `down -v` is not a safe demo reset.

## 12. Practical limits and next steps

- Other BRs remain in the original in-memory demo. The new source schema is a
  functional minimal OLTP path, not a migration of an external production LMS.
- The original Learner grading screen retains its group's demo path. BR4 uses
  the versioned operational assessment tables and reproducible source fixtures;
  importing a production grader requires mapping its versioned evaluations to
  those contracts. `/api/learning/activity` is the implemented real engagement
  write path and is exercised by browser acceptance tests.
- The hourly event-time slide is deliberate; it is not sub-second inactivity
  detection. The five-second browser poll is separate from the scoring boundary.
- Watermarks and deduplication are bounded. Older-than-horizon corrections need
  an isolated, coordinated backfill; changing slide/state schema requires a new
  checkpoint and consistent rebuild of window outputs.
- BR4 recomputes an affected materialization and uses JSONB joins. The measured
  100,000-evaluation correction costs about four seconds; finer dirty-partition
  processing or typed facts are reasonable future optimizations.
- Local tokens provide actual role/scope enforcement but do not replace a
  campus identity provider, token rotation or an application-wide login system.
- Raw/history retention, Kafka broker-volume lifecycle, backup coordination and
  horizontal scaling need operational policy before a production deployment.
- Real labeled dropout outcomes and full CDC throughput at 100,000 source rows
  were unavailable/unmeasured. The report distinguishes actual end-to-end latency
  from the separately measured streaming-stage throughput.

The supplied code, commands and evidence let an evaluator trace both BRs from
actual operational changes to persisted analytical output and displayed results.

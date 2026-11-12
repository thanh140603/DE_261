# BR4 and BR5 restoration

The restoration starts from main at `57a8c2b`. The working modules and two patch sets came from the older DE_261 checkout. The original October implementation report and engine evidence remain historical.

## Start the local stack

Run from the repository root with a running Docker daemon and Compose. The commands build the app and the Spark runtime from this checkout. Local demonstration tokens are displayed on the staff sign-in forms.

```sh
# Persistent source writes and analytics
EDU_BR45_CLOCK_MODE=manual docker compose --profile br45 up -d --build demo br45-cdc br45-stream
docker compose --profile br45 exec br45-cdc python -m edu_platform.br45.cli seed
```

Open the Instructor and Advisor views at port 8000. The fixture seeds source rows, including the manual clock. Allow time for Debezium, Spark and the dashboard polls. Run `python -m edu_platform.br45.cli recover` inside `br45-cdc` to write recovery activity. With wall clock mode, the default window advances hourly. Set `EDU_BR45_ASSESSMENT_ENGINE=postgres` on the Compose command to run BR4 jobs in PostgreSQL. BR5 continues to use Spark.

```sh
# Classroom, using isolated source rows, CDC, Kafka topics and checkpoints
read -rs EDU_BR45_CLASSROOM_PASSWORD
export EDU_BR45_CLASSROOM_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.br45-classroom.yml \
  up -d --build demo br45-classroom-cdc br45-classroom-stream

# Replay, using synthetic scenarios
docker compose -f docker-compose.yml -f docker-compose.br45-replay.yml up -d --build demo

# Isolated engine benchmark database and topics
bash infra/br45/run-engine-benchmark.sh prepare
bash infra/br45/run-engine-benchmark.sh br4 restoration-01
bash infra/br45/run-engine-benchmark.sh spark restoration-01
bash infra/br45/run-engine-benchmark.sh flink restoration-01
```

The classroom password applies on first initialization and must have at least 12 characters. Use `an.demo`, `chi.demo` or `ha.demo` on the learner page. Chi has prior activity and an overdue FizzBuzz lab. Start and complete lessons to write activity, then submit the lab to write its source submission and test results. Both dashboards use those identifiers. See [the classroom walkthrough](DE_261_BR45_DEMO.md) for fixture details.

The base profile stores Delta and checkpoints on the BR45 volume. The [MinIO overlay](../docker-compose.br45-v2.yml) puts Delta on MinIO and enables the shared Hive catalog. To populate the warehouse risk models, also start the existing lakehouse landing service and run the existing warehouse build as described in [the warehouse guide](architecture/data-warehouse.md).

## Contracts and runtime behavior

| Requirement | Implementation | Verification |
| --- | --- | --- |
| Additive upgrades | [Migration runner](../src/edu_platform/br45/db.py) and [lease and audit migration](../infra/postgres/br45_v3.sql) | PostgreSQL integration suite and repeated migration |
| BR4 CDC, snapshots, jobs and publication | [CDC worker](../src/edu_platform/br45/cdc.py), [Delta landing and Spark publication](../src/edu_platform/br45/lakehouse.py), [jobs](../src/edu_platform/br45/jobs.py) | [PostgreSQL integration](../tests/integration/test_br45.py), [independent source oracle](../src/edu_platform/br45/oracle.py), [labeled cases](evidence/br45-restoration/br4-labeled.json) |
| BR5 signed event-time windows and risk | [Streaming job](../src/edu_platform/br45/streaming.py), [risk policy and alerts](../src/edu_platform/br45/risk.py) | [Risk and window tests](../tests/unit/test_br45.py), [full pipeline harness](../src/edu_platform/br45/verify.py) |
| Advisor policy and intervention | [Policy and note endpoints](../src/edu_platform/br45/api.py), [outbox](../src/edu_platform/br45/events.py), [warehouse transitions](../warehouse/transform/silver/dropout_alert_transitions.sql) | Scoped policy conflicts, retries, actor audit and boundary activation in [PostgreSQL integration](../tests/integration/test_br45.py) |
| Classroom and replay | [Classroom](../src/edu_platform/br45/classroom.py), [replay](../src/edu_platform/br45/replay.py), [React dashboard](../apps/web/src/App.tsx) | [Ownership and logout](../tests/unit/test_classroom_accounts.py), [replay contract](../tests/unit/test_br45_replay.py) |
| BR5 effectiveness | [OULAD evaluator](../src/edu_platform/br45/effectiveness.py) | [New OULAD results](evidence/br45-restoration/oulad/oulad_evaluation.json), [historical runs](evidence/br45-v2/oulad_evaluation.json) |
| Engine comparisons | [Engine harness](../infra/br45/run-engine-benchmark.sh) | [Historical raw results and restart logs](evidence/br45-v2/engine-comparison/) |

FastAPI serves the mode-specific OpenAPI document at `/openapi.json`. [JSON Schemas](../schemas/br45/v2/) cover the new request and response models.

- `POST /api/instructor/courses/{course_id}/assessment-jobs` accepts an optional UTC date range and returns the durable job. Poll `GET /api/instructor/assessment-jobs/{job_id}`. Instructor read endpoints retain the last successful rows and report the published revision, pending revision, engine, computation time and Delta version.
- `GET` and `PUT /api/advisor/courses/{course_id}/policy` are advisor-scoped. PUT requires the current version and a parameter object. A stale version returns 409. The new policy is eligible at the next completed boundary.
- `GET` and `POST /api/advisor/alerts/{alert_id}/notes` are advisor-scoped. POST requires a note and an idempotency key. Reusing the key with a different note returns 409.

## Diagnose, recover and upgrade

Use `python -m edu_platform.br45.cli diagnostics --connect-url http://connect:8083` from `br45-cdc` to check the connector. `GET /api/analytics/diagnostics` shows accepted offsets, outbox backlog, quarantined records, the watermark, committed feature progress, failed jobs and mart publication times. Retention previews by default with `python -m edu_platform.br45.cli retention --days 60`. Use `--apply` after reviewing the preview. It prunes only acknowledged activity deliveries older than the watermark and retention interval, and blocks while publishers or jobs are pending.

For an existing v1 deployment, take a cold backup before building v2. If Kafka used an anonymous volume, copy its stopped data into the new named Kafka volume before starting the new broker. Keep the same broker cluster ID, connector offsets and source identity. The new stream uses a versioned checkpoint based on topic and window configuration. Check that the retained activity topic still covers the windows needed at startup. Use the isolated rebuild below if the old topic cannot supply them.

### Coordinated cold backup and restore

1. Stop writers and wait for outbox delivery, stream catch-up and terminal assessment jobs. Capture diagnostics, the exact Compose files and environment values, image digests and `docker inspect` volume mappings. Keep credentials out of shared evidence.
2. Stop the BR45 workers, warehouse writers, Connect, Kafka, PostgreSQL and MinIO. While they are stopped, archive the mapped PostgreSQL, Kafka, MinIO, metastore and checkpoint volumes with their file ownership. Include Delta data with the checkpoint volume for the base profile. Kafka data includes Connect's offsets and config topics.
3. Restore into fresh volumes with the recorded image versions, cluster ID, network listener settings and checkpoint paths. Start PostgreSQL, MinIO and Kafka, then Connect, then the BR45 workers and API. Confirm WAL slot, connector and consumer progress before enabling source writes.
4. Verify a known mart, one risk history, a duplicate delivery and a new event before accepting the restore. Keep the original volumes available for rollback. Routine fixture reset is scoped to `br45-demo-*` rows.

For the verification deployment with BR4 on MinIO, use the scoped volume helper after stopping the project. It archives PostgreSQL, Kafka, MinIO and Spark checkpoints, verifies SHA-256 checksums, and restores only to an unused project name.

```sh
bash infra/br45/cold-volume-copy.sh backup de261-br45-verify "$ARCHIVE"
bash infra/br45/cold-volume-copy.sh restore de261-br45-restore "$ARCHIVE"
docker compose -p de261-br45-restore -f docker-compose.yml -f infra/br45/compose.verify.yml   --profile br45 up -d demo br45-cdc br45-stream
```

Use the same clock mode and image digests after restore. The verification overlay publishes fixed loopback ports, so stop the verification project before starting its restored copy. Include the separate metastore volume in a deployment that uses Hive.

### Rebuild after a change beyond the watermark

Quarantined events remain available with their original envelope. The rebuild reads the authoritative source snapshot, including the effects of late corrections and deletions.

1. Pause source writes, record the clock and back up the active environment. Create an empty `br45_rebuild_<run>` database and run `python -m edu_platform.br45.cli backfill --target-dsn "$REBUILD_DSN"`. The command copies and checks each source table, immutable policies, risk history, alerts and intervention notes in a separate database.
2. In a separate Compose deployment, set the BR45 DSN to the replacement database and use unique `EDU_BR45_CDC_IDENTITY`, `EDU_BR45_TOPIC_PREFIX` (ending in `.br45.`), `EDU_BR45_LANDING_GROUP`, activity, clean and domain topics, checkpoint and lakehouse paths. Ensure the source host and port in the connector are reachable from Connect. Initialize and let the replacement stream catch up before changing where the API reads.
3. Compare rebuilt seven-day and prior-week counts, published revisions, and expected corrections for the affected courses. The staging command preserves prior risk history, alert IDs and intervention notes. Keep the original database as the rollback source. Redirect the API and source writers together after validation. Keep the old runtime stopped with its volumes intact for rollback.

## Results and limits

The new PostgreSQL runs include lease fencing, policy activation and note idempotency. Four labeled synthetic BR4 scenarios matched their expected states and the independent oracle agreed with PostgreSQL counts. The OULAD rerun consumed 10,655,280 daily-aggregate VLE rows and produced 77,106 observations. Threshold 65 tied version 1 on the 2013 validation set, so version 1 was retained. The 2014 results had been inspected previously and are a retrospective evaluation.

Run the full Compose acceptance, fresh Docker image build, and coordinated backup and restore on a host with Docker access. Historic engine results are retained for comparison. The Docker-dependent gates for this checkout are pending.

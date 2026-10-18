# DE_261 - Education Data Platform

Data engineering platform for a large-scale online education system. It turns
four raw sources - clickstream telemetry, PostgreSQL CDC, an unstructured course
corpus and sandbox execution logs - into stores for learning analytics, adaptive
recommendation and early drop-out detection. Requirements: `docs/DE_261.pdf`.

## Requirement -> pipeline map

| BR | Stakeholder | Need | Bounded context | Runtime |
|----|-------------|------|-----------------|---------|
| BR1 | Learner | Real-time course notifications | `notification` | Kafka consumer service + Redis |
| BR2 | Learner | Real-time next-step recommendation | `recommendation` | Spark batch + Flink session features -> Feature Store (Delta / Redis) |
| BR3 | Learner | Detailed feedback on code/SQL submissions | `grading` | Kafka-buffered ingestion service |
| BR4 | Instructor | Abnormal fail-rate questions / test cases | `analytics` + `br45` | CDC -> SQL -> PostgreSQL marts (serving); history in lakehouse `mart.assessment_item_stats` |
| BR5 | Advisor | Early drop-out warning | `risk` + `br45` | Debezium CDC -> Spark event-time windows -> alerts; history in `gold.fct_risk_score_daily` / `fct_dropout_alert` |
| BR6 | Admin / B2B | Org skill progress & completion | `telemetry` + `analytics` | Medallion (bronze/silver/gold), PII pseudonymisation, `mart.org_progress` with min-cohort k=5 |
| BR7 | Instructor | Video interaction heatmap | `analytics` | `mart.video_heatmap` per video version (Spark) + Flink live overlay in Redis |
| BR8 | Instructor | Cache / search sync on content change; engagement trend | `content` + `analytics` | Kafka consumer service; `mart.engagement_trend` (weekly) + `gold.fct_content_sync` |

## Architecture in one paragraph

Kafka (+ Debezium) is the ingestion and event bus. Flink handles stateful,
event-time streaming (session features, low-latency normalisation) and
publishes to Kafka / Redis; BR5 risk windows run on Spark Structured Streaming
(ADR 0009). Spark is the only writer of the lakehouse: Structured Streaming
lands Kafka into bronze and silver, batch builds gold, marts and features.
Delta Lake on object storage (MinIO locally) is the lakehouse (ACID, time
travel, Change Data Feed); its gold layer is the data warehouse - a Kimball
star schema cataloged in the Hive Metastore and served by Trino (ADR 0010-0012).
Redis is the low-latency serving layer (online features, risk scores,
notification dedup/rate-limit). Every pipeline is modelled as a DDD bounded
context with hexagonal layers so the same use case runs unchanged on Flink or
Spark and can be unit-tested without an engine.
Details: `docs/architecture/overview.md`, `docs/architecture/data-warehouse.md`,
`docs/architecture/pipelines.md`; decisions: `docs/adr/`.


## BR4 and BR5: persistent implementation

BR4 and BR5 now have a real PostgreSQL → Debezium → Kafka path, persistent
analytical results, scoped APIs and integrated dashboards. BR5 uses Spark
Structured Streaming event-time windows. The other BRs retain the original demo.

```bash
docker compose --profile br45 up -d --build demo br45-init br45-cdc br45-stream
docker compose exec -T br45-cdc python -m edu_platform.br45.cli seed
```

Open Instructor or Advisor at `http://localhost:8000`. For the local synthetic
demo, connect with `instructor-demo` or `advisor-demo` respectively. The assessment
fixture is under Python for Data. Set `EDU_BR45_AUTH` for private identities and
explicit course scopes.

**What was done, exact metric rules, changed files, tests, measured benchmarks,
screenshots and the complete demonstration runbook:**
[BR4/BR5 implementation document](docs/BR4_BR5_IMPLEMENTATION.md).

Use `docker compose --profile br45 stop` to preserve demonstration state.
`down -v` deletes shared data and is not the BR4/BR5 reset command.

## Layout

```
src/edu_platform/
  shared_kernel/     Entity, ValueObject, AggregateRoot, DomainEvent, ports (no I/O)
  platform/          config, logging, Kafka/Redis/Delta/Spark/Flink factories
  contexts/<bc>/     domain/ application/ infrastructure/   (one per bounded context)
  entrypoints/       streaming/ (Flink)  batch/ (Spark)  services/  cli.py
schemas/             versioned data contracts (JSON Schema, feature registry)
warehouse/           lakehouse warehouse as code: ddl/, transform/ (silver, gold, mart, features),
                     quality/ gates, models.yaml registry (run by platform/warehouse)
infra/               docker-compose services config: Debezium, Kafka topics, OLTP seed, MinIO, Spark
                     image, Hive Metastore, Trino catalog + access rules, k8s/terraform
orchestration/       Airflow DAGs for batch cadences
tests/               unit (pure, incl. architecture guardrails), integration, e2e
docs/                requirements, architecture, ADRs
```

Dependency rule: `domain <- application <- infrastructure <- entrypoints`.
Contexts never import each other; they integrate through Kafka topics and
lakehouse tables. `tests/unit/test_architecture.py` enforces this.

## Run the demo (web client + server)

Needs only Docker Desktop (or Docker Engine + Compose):

```bash
docker compose up -d --build     # whole stack; demo at http://localhost:8000 (DEMO_PORT to change)
docker compose down -v           # stop and drop data
```

One `docker-compose.yml` starts everything: the demo container (client built by
Node, server on Python, see `Dockerfile`) plus Kafka, Kafka UI (:8090), Schema
Registry, Debezium Connect, Postgres, Redis, MinIO (:9001), Hive Metastore
(:9083), Trino (:8091), Flink (:8082) and Spark (:8080). The original demo pipelines run in-process (ADR 0008). The opt-in `br45` profile
adds the working persistent BR4/BR5 path described above; other production
adapters remain unfinished.

MinIO server and client are built locally from pinned official source releases
using `infra/minio/Dockerfile`; the stack does not pull `minio/minio` or `minio/mc`.
The first build downloads Go dependencies and can take several minutes. To pull
only prebuilt services, use `docker compose pull --ignore-buildable`.

Postgres is available to host tools at `localhost:5433` (`lms` user, password and
database). Set `POSTGRES_PORT` to change this port; containers use `postgres:5432`.
The default avoids a conflict with a PostgreSQL service already running on the host.

## Run the lakehouse warehouse

```bash
docker compose up -d minio minio-init metastore-db hive-metastore trino
docker compose run --rm spark-jobs edu warehouse bootstrap               # 6 schemas, 50 Delta tables
docker compose run --rm spark-jobs edu warehouse seed-bronze --end-date 2026-10-17 --days 35
docker compose run --rm spark-jobs edu warehouse run --run-date 2026-10-17 --start-date 2026-08-01
docker exec -it de261-trino trino --user analyst --catalog lakehouse   # query silver/gold/mart
```

For the real streaming path register `infra/debezium/postgres-connector.json`, create
topics with `edu infra create-topics infra/kafka/topics.yaml`, and start
`docker compose --profile pipelines up -d lakehouse-streaming`. Pipeline catalogue,
schedules (Airflow DAGs in `orchestration/airflow/dags`) and replay procedures:
`docs/architecture/pipelines.md`; warehouse model: `docs/architecture/data-warehouse.md`.

The other demo pipelines run in one process with in-memory adapters behind
the same ports the production entrypoints use (ADR 0008). What to show:

| View | Requirement | Try |
|------|-------------|-----|
| Learner | BR1, BR2, BR3 | send a deadline reminder, watch a lesson, submit the starter code and read the feedback |
| Instructor | BR4, BR7, BR8 | connect to persistent assessment health with the `br45` profile; simulate views or publish content in the other demo panels |
| Advisor | BR5 | connect to persistent risk and alerts with the `br45` profile; follow the runbook for CDC recovery |
| Admin | BR6 | compare Acme (reported) with Globex (suppressed, fewer than 5 learners) |
| Pipeline | BR6 | start the simulator; send a schema 1.0, late or malformed event and follow it to silver or the DLQ |

API contract: `docs/api.md`.

## Developer commands

Only for changing the code. Create a virtualenv first: `python -m venv .venv` then `.venv/Scripts/pip install -e ".[demo,dev]"`.

```bash
# run the server and client separately with hot reload
PYTHONPATH=src .venv/Scripts/python -m uvicorn edu_platform.entrypoints.api.main:app --port 8000 --reload
cd apps/web && npm install && npm run dev            # http://localhost:5173, proxies /api to :8000

# quality gates (same as CI)
.venv/Scripts/ruff check src tests && .venv/Scripts/ruff format --check src tests
.venv/Scripts/mypy
PYTHONPATH=src .venv/Scripts/python -m pytest tests/unit

# platform stack helpers (after docker compose up -d)
curl -s -X POST -H "Content-Type: application/json" --data @infra/debezium/postgres-connector.json http://localhost:8083/connectors   # register Debezium CDC
docker exec -i de261-postgres psql -U lms -d lms < infra/postgres/init.sql                                                       # re-seed OLTP schema
PYTHONPATH=src .venv/Scripts/python -m edu_platform.entrypoints.cli infra create-topics infra/kafka/topics.yaml                   # create missing topics
docker compose logs -f --tail=100                                                                                                # tail the stack
```

On macOS/Linux replace `.venv/Scripts/python` with `.venv/bin/python`.

## Status

Domain and application logic for all seven contexts is implemented and unit
tested; the demo runtime and web client exercise it end to end. The persistent
BR4/BR5 runtime, CDC connector, jobs, dashboards, tests and
measured evaluation are implemented; see `docs/BR4_BR5_IMPLEMENTATION.md`. The
lakehouse path is implemented and verified on the local stack: Debezium CDC and
Kafka landing into bronze, bronze -> silver (streaming and batch), the gold star
schema, the BR4/BR6/BR7/BR8 marts, the BR2 offline features, quality gates,
maintenance and the Airflow DAGs. Still documented `TODO` stubs: the remaining
Flink jobs, the Kafka consumer services, Redis adapters (online feature
materialisation), corpus chunking/embedding and OpenSearch.

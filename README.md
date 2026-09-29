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
| BR4 | Instructor | Abnormal fail-rate questions / test cases | `analytics` | Spark gold mart |
| BR5 | Advisor | Early drop-out warning | `risk` | Debezium CDC -> Flink sliding window |
| BR6 | Admin / B2B | Org skill progress & completion | `telemetry` + `analytics` | Medallion (bronze/silver/gold), PII pseudonymisation, min-cohort |
| BR7 | Instructor | Video interaction heatmap | `analytics` | Per-second aggregation (Spark + Flink fast path) |
| BR8 | Instructor | Cache / search sync on content change; engagement trend | `content` + `analytics` | Kafka consumer service + windowed Spark/Flink |

## Architecture in one paragraph

Kafka (+ Debezium) is the ingestion and event bus. Flink handles stateful,
event-time streaming (risk windows, session features, low-latency
normalisation); Spark handles batch (medallion, long-term features, corpus
chunking/embedding, marts). Delta Lake on object storage is the lakehouse
(ACID, time travel, Change Data Feed); Redis is the low-latency serving layer
(online features, risk scores, notification dedup/rate-limit). Every pipeline
is modelled as a DDD bounded context with hexagonal layers so the same use case
runs unchanged on Flink or Spark and can be unit-tested without an engine.
Details: `docs/architecture/overview.md`, decisions: `docs/adr/`.

## Layout

```
src/edu_platform/
  shared_kernel/     Entity, ValueObject, AggregateRoot, DomainEvent, ports (no I/O)
  platform/          config, logging, Kafka/Redis/Delta/Spark/Flink factories
  contexts/<bc>/     domain/ application/ infrastructure/   (one per bounded context)
  entrypoints/       streaming/ (Flink)  batch/ (Spark)  services/  cli.py
schemas/             versioned data contracts (JSON Schema, feature registry)
infra/               docker-compose local stack, Debezium, Kafka topics, OLTP seed, k8s/terraform
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
Registry, Debezium Connect, Postgres, Redis, MinIO (:9001), Flink (:8082) and
Spark (:8080). The demo runs its pipelines in-process (ADR 0008); the other
services are the production path whose adapters are still TODO stubs.

Demo mode runs every pipeline in one process with in-memory adapters behind
the same ports the production entrypoints use (ADR 0008). What to show:

| View | Requirement | Try |
|------|-------------|-----|
| Learner | BR1, BR2, BR3 | send a deadline reminder, watch a lesson, submit the starter code and read the feedback |
| Instructor | BR4, BR7, BR8 | run "broken test case", simulate 200 viewing events, publish a new transcript version |
| Advisor | BR5 | run "at-risk learner" and watch the risk score cross the threshold |
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
PYTHONPATH=src .venv/Scripts/python -m edu_platform.entrypoints.cli infra create-topics infra/kafka/topics.yaml                   # TODO: topic creation
docker compose logs -f --tail=100                                                                                                # tail the stack
```

On macOS/Linux replace `.venv/Scripts/python` with `.venv/bin/python`.

## Status

Domain and application logic for all seven contexts is implemented and unit
tested; the demo runtime and web client exercise it end to end. Production
adapters and entrypoints (Kafka, Debezium, Flink jobs, Spark jobs, Delta,
Redis, Airflow DAGs) are documented stubs marked `TODO` in their module
docstrings.

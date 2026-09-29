# ADR 0006: Redis as the low-latency serving layer

Status: accepted - 2026-09-29

## Context
Recommender lookups (< 10 ms), advisor risk dashboards and notification dedup/rate-limit need sub-millisecond keyed access with TTLs.

## Decision
Redis (cluster mode in prod) for online feature store, risk scores and notification state, with TTL = freshness SLA. Cassandra deferred until dataset exceeds memory budget; adapters are behind ports so the swap is local to infrastructure/.

## Consequences
Redis is not the system of record: everything is rebuildable from the lakehouse.

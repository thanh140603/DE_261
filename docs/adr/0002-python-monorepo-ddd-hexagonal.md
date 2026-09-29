# ADR 0002: Python monorepo with DDD bounded contexts and hexagonal layers

Status: accepted - 2026-09-29

## Context
Eight business requirements map to distinct pipelines with different cadences (streaming, batch, services) but shared concepts (learner, course, events). Team is Python-first; PySpark and PyFlink cover both engines.

## Decision
One repository, one package (edu_platform). Each pipeline family is a bounded context with domain / application / infrastructure layers; contexts communicate only via Kafka topics and lakehouse tables. Use cases are engine-agnostic so the same NormalizeEvents runs in Flink (fast path) and Spark (backfill). Alternatives rejected: one repo per pipeline (duplicated kernel, drift), Scala/Java for Flink (team skill mismatch; revisit if PyFlink performance becomes the bottleneck).

## Consequences
Clear ownership and testability without an engine; architecture test enforces layering. Cost: some indirection (ports/adapters) and PyFlink limits for very hot operators.

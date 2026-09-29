"""edu_platform - data engineering platform for a large-scale online education system.

Package layout (see docs/architecture/overview.md):

    shared_kernel/   DDD building blocks shared by every bounded context (no I/O).
    platform/        Cross-cutting infrastructure: config, logging, Kafka/Redis/Delta clients.
    contexts/        One package per bounded context, each split into
                     domain / application / infrastructure (hexagonal).
    entrypoints/     Thin composition roots: Flink jobs, Spark jobs, services, CLI.

Dependency rule (enforced by tests/unit/test_architecture.py):
    domain  <-  application  <-  infrastructure  <-  entrypoints
    domain never imports application/infrastructure/platform.
"""

__version__ = "0.1.0"

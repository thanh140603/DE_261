"""Composition roots. Each module wires adapters into use cases and starts an engine.
No business logic here - only dependency injection and engine bootstrap.

    streaming/   PyFlink jobs   (long-running, stateful, event-time)
    batch/       Spark jobs     (scheduled by Airflow, idempotent per partition)
    services/    Kafka consumers / HTTP services (containerised, horizontally scalable)
    cli.py       `edu` command - runs any of the above locally
"""

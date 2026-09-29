"""Demo runtime: runs every pipeline in one process with in-memory adapters.

This is the composition root used by the demo web server. It replaces
Kafka/Flink/Spark/Delta/Redis with in-process equivalents behind the same
ports, so the domain and application code that runs here is exactly what the
production entrypoints wire to real infrastructure.
"""

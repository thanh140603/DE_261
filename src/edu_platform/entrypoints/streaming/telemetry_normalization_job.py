"""Flink job: telemetry_normalization_job (BR6 step 2, low-latency path).

Content (TODO):
- Source: telemetry.events.raw.v1 (watermark: 5 min bounded out-of-orderness).
- Per event: validate -> migrate schema -> pseudonymise -> map to LearningEvent.
- Sinks: telemetry.learning_events.v1 (Kafka, consumed by the other Flink jobs) and
  telemetry.events.dlq.v1 ({"reason", "payload"}). Not Delta: Spark owns every lakehouse
  write and normalises bronze with the same use case (ADR 0010).
- Late events beyond watermark are still emitted, flagged is_late=true.
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

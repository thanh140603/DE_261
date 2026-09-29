"""Flink job: telemetry_normalization_job (BR6 step 2, low-latency path).

Content (TODO):
- Source: telemetry.events.raw.v1 (watermark: 5 min bounded out-of-orderness).
- Per event: validate -> migrate schema -> pseudonymise -> map to LearningEvent.
- Sinks: silver.learning_events (Delta, via Flink Delta connector) + telemetry.events.dlq.v1.
- Late events beyond watermark are still written, flagged extensions.late=true.
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

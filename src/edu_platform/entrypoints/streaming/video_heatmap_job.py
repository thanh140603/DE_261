"""Flink job: video_heatmap_job (BR7 near-real-time variant).

Content (TODO):
- Source: telemetry.learning_events.v1 filtered to played/paused/seeked with video_position.
- Key by (content_id, second); tumbling 5 min windows; increments into Redis hashes
  edu:heatmap:<content_id>:<date> (TTL 48 h) = live overlay for today. The authoritative
  heatmap is the warehouse mart.video_heatmap (Spark, ADR 0010: Flink does not write Delta).
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

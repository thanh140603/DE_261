"""Flink job: video_heatmap_job (BR7 near-real-time variant).

Content (TODO):
- Source: silver learning events filtered to played/paused/seeked with video_position.
- Key by (content_id, second); tumbling 5 min windows; incremental counts merged into
  gold.video_heatmap via upsert.
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

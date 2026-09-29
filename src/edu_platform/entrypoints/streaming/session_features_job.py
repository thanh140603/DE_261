"""Flink job: session_features_job (BR2 streaming branch).

Content (TODO):
- Source: silver learning events stream (or raw topic post-normalisation).
- Key by learner; session windows with 30 min gap; ComputeSessionFeatures in keyed state.
- Sinks: Redis online feature store (put_session) + features.session.v1.
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

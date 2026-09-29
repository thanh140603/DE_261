"""PyFlink environment factory.

Content (TODO):
- ``build_stream_env(job_name, settings)``: StreamExecutionEnvironment with
  exactly-once checkpointing, RocksDB state backend, event-time, fixed-delay
  restart strategy, parallelism from env.
- ``kafka_source(topic, group_id, watermark_strategy)`` using KafkaSource with
  bounded out-of-orderness watermarks (mobile events arrive late / out of order).
- ``kafka_sink(topic)`` with exactly-once delivery.
- Watermark presets: TELEMETRY (5 min lateness), CDC (10 s).
"""

from __future__ import annotations

from typing import Any

from edu_platform.platform.config import Settings


def build_stream_env(job_name: str, settings: Settings) -> Any:
    raise NotImplementedError  # TODO: see module docstring

"""EventValidator adapter mirroring /schemas/telemetry/v1/learning_event.schema.json.

Kept dependency-free so it runs identically inside Flink, Spark and the demo.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edu_platform.contexts.telemetry.domain.events import Platform, Verb

REQUIRED = ("event_id", "learner_id", "course_id", "session_id", "verb", "occurred_at")


class LearningEventValidator:
    def validate(self, payload: dict[str, Any]) -> list[str]:
        errors = [f"missing field {f!r}" for f in REQUIRED if not payload.get(f)]
        if errors:
            return errors
        if payload["verb"] not in Verb.__members__.values():
            errors.append(f"unknown verb {payload['verb']!r}")
        if payload.get("platform", "web") not in Platform.__members__.values():
            errors.append(f"unknown platform {payload['platform']!r}")
        try:
            datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
        except ValueError:
            errors.append("occurred_at is not ISO-8601")
        pos = payload.get("video_position_sec")
        if pos is not None and (not isinstance(pos, int) or pos < 0):
            errors.append("video_position_sec must be a non-negative integer")
        return errors

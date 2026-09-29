"""Telemetry domain model: an xAPI/Caliper-like learning statement.

Narrower than full xAPI on purpose: only the fields downstream contexts consume
are first-class; the rest travels in ``extensions``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from edu_platform.shared_kernel.domain import InvariantViolation, ValueObject
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId, LearnerId, SessionId


class Verb(StrEnum):
    """Closed vocabulary of learning actions. Unknown verbs go to the DLQ, never to silver."""

    LOGGED_IN = "logged_in"
    VIEWED = "viewed"
    PLAYED = "played"
    PAUSED = "paused"
    SEEKED = "seeked"  # rewind / forward on video (BR7)
    COMPLETED = "completed"
    ATTEMPTED = "attempted"
    SUBMITTED = "submitted"
    POSTED = "posted"  # discussion (BR8 engagement)


class Platform(StrEnum):
    WEB = "web"
    ANDROID = "android"
    IOS = "ios"


@dataclass(frozen=True)
class SchemaVersion(ValueObject):
    """Semantic version of the client payload schema. Drives migrations to the current version."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        if self.major < 1 or self.minor < 0:
            raise InvariantViolation(f"invalid schema version {self.major}.{self.minor}")

    @classmethod
    def parse(cls, raw: str) -> SchemaVersion:
        major, _, minor = str(raw).partition(".")
        try:
            return cls(int(major), int(minor or 0))
        except ValueError as exc:
            raise InvariantViolation(f"unparseable schema version {raw!r}") from exc

    def __lt__(self, other: SchemaVersion) -> bool:
        return (self.major, self.minor) < (other.major, other.minor)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"


CURRENT_SCHEMA_VERSION = SchemaVersion(1, 1)


@dataclass(frozen=True)
class LatenessPolicy(ValueObject):
    """Bounded out-of-orderness accepted by streaming windows (mobile offline replay)."""

    max_lateness: timedelta = timedelta(minutes=5)

    def is_late(self, occurred_at: datetime, received_at: datetime) -> bool:
        return received_at - occurred_at > self.max_lateness


@dataclass(frozen=True)
class VideoPosition(ValueObject):
    """Playback position in whole seconds (bucket key for the BR7 heatmap)."""

    second: int

    def __post_init__(self) -> None:
        if self.second < 0:
            raise InvariantViolation("video position cannot be negative")


@dataclass(frozen=True)
class LearningEvent(ValueObject):
    """Normalised (silver) event. ``learner_pseudonym`` replaces the raw learner id."""

    event_id: str
    schema_version: SchemaVersion
    learner_pseudonym: str
    course_id: CourseId
    content_id: ContentId | None
    session_id: SessionId
    verb: Verb
    platform: Platform
    occurred_at: datetime  # event time from the device
    received_at: datetime  # ingestion time; occurred_at << received_at means late data
    video_position: VideoPosition | None = None
    is_late: bool = False
    extensions: dict[str, Any] = field(default_factory=dict)

    @property
    def lateness_seconds(self) -> float:
        return (self.received_at - self.occurred_at).total_seconds()


@dataclass(frozen=True)
class RawEvent(ValueObject):
    """Bronze record: whatever the client sent, plus ingestion metadata. Never mutated."""

    event_id: str
    raw_learner_id: LearnerId
    schema_version: SchemaVersion
    payload: dict[str, Any]
    received_at: datetime
    source_topic: str
    partition: int
    offset: int

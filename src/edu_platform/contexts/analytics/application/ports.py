"""Read side of the BR6/BR7/BR8 marts (served from the lakehouse, ADR 0010).

The marts are built by Spark (warehouse/transform/mart); serving only reads them. Read
models mirror the mart rows one to one: suppression (k-anonymity), intensities and decline
flags are decided by the warehouse and never recomputed or relaxed at serving time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class MartUnavailable(Exception):
    """The SQL warehouse cannot be reached or rejected the query."""


@dataclass(frozen=True)
class NamedRef:
    id: str
    name: str | None


# --- BR6 ----------------------------------------------------------------------
@dataclass(frozen=True)
class OrgProgressRow:
    course_id: str
    course_title: str | None
    skill: str | None
    cohort_size: int
    completion_rate: float | None  # None when suppressed
    avg_mastery: float | None
    completed_learners: int | None
    suppressed: bool


@dataclass(frozen=True)
class OrgProgressSnapshot:
    organisation_id: str
    organisation_name: str | None
    as_of: date
    min_cohort: int
    built_at: datetime
    rows: list[OrgProgressRow]


# --- BR7 ----------------------------------------------------------------------
@dataclass(frozen=True)
class VideoVersion:
    content_id: str
    version: int | None  # None = inferred content without a CDC version row yet
    title: str | None
    course_id: str | None
    duration_sec: int | None


@dataclass(frozen=True)
class HeatmapSecond:
    second: int
    play: int
    pause: int
    seek: int
    learners: int
    intensity: float


@dataclass(frozen=True)
class VideoHeatmapSnapshot:
    video: VideoVersion
    as_of: date
    window_days: int
    built_at: datetime
    seconds: list[HeatmapSecond]


# --- BR8 ----------------------------------------------------------------------
@dataclass(frozen=True)
class EngagementSeries:
    learner_pseudonym: str
    scores: list[float]  # oldest window first
    deltas: list[float | None]
    declining: bool


@dataclass(frozen=True)
class EngagementTrendSnapshot:
    course_id: str
    as_of: date
    week_starts: list[date]
    course_avg: list[float]
    decline_ratio: float
    built_at: datetime
    learners: list[EngagementSeries]


class AnalyticsMartReader(Protocol):
    def organisations(self, ids: list[str]) -> list[NamedRef]: ...

    def courses(self, ids: list[str]) -> list[NamedRef]: ...

    def org_progress(self, organisation_id: str, as_of: date | None) -> OrgProgressSnapshot | None:
        """Latest snapshot on or before ``as_of`` (latest overall when None)."""
        ...

    def course_videos(self, course_id: str) -> list[VideoVersion]: ...

    def video(self, content_id: str) -> list[VideoVersion]:
        """Every version of a video present in the heatmap mart, newest first."""
        ...

    def video_heatmap(self, content_id: str, version: int | None) -> VideoHeatmapSnapshot | None:
        """Heatmap of one version (the newest when None)."""
        ...

    def engagement_trend(
        self, course_id: str, as_of: date | None
    ) -> EngagementTrendSnapshot | None:
        """Latest snapshot on or before ``as_of`` (latest overall when None)."""
        ...


# --- live overlays (BR7/BR8, streaming, today only) ------------------------------------
@dataclass(frozen=True)
class LiveSecond:
    second: int
    play: int
    pause: int
    seek: int
    learners: int  # approximate distinct learners (HyperLogLog), per day


@dataclass(frozen=True)
class LiveHeatmap:
    content_id: str
    days: list[date]  # days that contributed (after the mart snapshot)
    updated_at: datetime | None
    seconds: list[LiveSecond]  # summed over ``days``, unclamped positions


@dataclass(frozen=True)
class LiveEngagement:
    course_id: str
    day: date
    updated_at: datetime | None
    scores: dict[str, float]  # learner pseudonym -> engagement points so far today


class LiveOverlayReader(Protocol):
    """Event-time aggregates the streaming job keeps in Redis for days the marts do not
    cover yet. Approximate by design: events later than the watermark only reach the marts."""

    def heatmap(self, content_id: str, days: list[date]) -> LiveHeatmap: ...

    def engagement(self, course_id: str, day: date) -> LiveEngagement: ...

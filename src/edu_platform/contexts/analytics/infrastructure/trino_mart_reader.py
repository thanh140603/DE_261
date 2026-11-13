"""AnalyticsMartReader over the lakehouse SQL warehouse (Trino, ADR 0010).

Queries are plain ANSI SQL with positional ``?`` parameters, so the same reader also runs
on a Spark session (``catalog=None``) - which is how its SQL is tested without Trino.
Trino connects as the read-only ``app`` user (infra/trino/rules.json: gold + mart only).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from edu_platform.contexts.analytics.application.ports import (
    EngagementSeries,
    EngagementTrendSnapshot,
    HeatmapSecond,
    MartUnavailable,
    NamedRef,
    OrgProgressRow,
    OrgProgressSnapshot,
    VideoHeatmapSnapshot,
    VideoVersion,
)
from edu_platform.platform.config import TrinoSettings

Row = dict[str, Any]
Query = Callable[[str, list[Any]], list[Row]]

_LATEST = date(9999, 12, 31)
_NO_VERSION = -1  # inferred content without a CDC version row


def trino_query(settings: TrinoSettings) -> Query:
    """Query function backed by the Trino DBAPI client (one connection per call)."""

    def query(sql: str, params: list[Any]) -> list[Row]:
        import trino

        connect: Callable[..., Any] = trino.dbapi.connect
        try:
            conn = connect(
                host=settings.host,
                port=settings.port,
                user=settings.user,
                catalog=settings.catalog,
                http_scheme=settings.http_scheme,
                request_timeout=settings.timeout_seconds,
            )
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                names = [d[0] for d in cur.description or []]
                return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]
            finally:
                conn.close()
        # DBAPI errors, HTTP errors and connection failures (requests' errors are OSErrors)
        except (trino.exceptions.Error, trino.exceptions.HttpError, OSError) as exc:
            raise MartUnavailable(str(exc)) from exc

    return query


class TrinoMartReader:
    def __init__(self, query: Query, catalog: str | None = "lakehouse") -> None:
        self._query = query
        self._prefix = f"{catalog}." if catalog else ""

    def _t(self, name: str) -> str:
        return f"{self._prefix}{name}"

    @staticmethod
    def _in(ids: list[str]) -> str:
        return ", ".join("?" for _ in ids)

    # --- reference ----------------------------------------------------------------
    def organisations(self, ids: list[str]) -> list[NamedRef]:
        if not ids:
            return []
        rows = self._query(
            "SELECT organisation_id, organisation_name "
            f"FROM {self._t('gold.dim_organisation')} WHERE organisation_id IN ({self._in(ids)}) "
            "ORDER BY organisation_name, organisation_id",
            list(ids),
        )
        return [NamedRef(r["organisation_id"], r["organisation_name"]) for r in rows]

    def courses(self, ids: list[str]) -> list[NamedRef]:
        if not ids:
            return []
        rows = self._query(
            f"SELECT course_id, course_title FROM {self._t('gold.dim_course')} "
            f"WHERE course_id IN ({self._in(ids)}) ORDER BY course_title, course_id",
            list(ids),
        )
        return [NamedRef(r["course_id"], r["course_title"]) for r in rows]

    # --- BR6 ----------------------------------------------------------------------
    def org_progress(self, organisation_id: str, as_of: date | None) -> OrgProgressSnapshot | None:
        table = self._t("mart.org_progress")
        rows = self._query(
            "SELECT as_of_date, organisation_name, course_id, course_title, skill, cohort_size, "
            "completion_rate, avg_mastery, completed_learners, is_suppressed, min_cohort_k, "
            f"_built_at FROM {table} WHERE organisation_id = ? AND as_of_date = ("
            f"SELECT max(as_of_date) FROM {table} WHERE organisation_id = ? AND as_of_date <= ?) "
            "ORDER BY course_title, course_id",
            [organisation_id, organisation_id, as_of or _LATEST],
        )
        if not rows:
            return None
        first = rows[0]
        return OrgProgressSnapshot(
            organisation_id=organisation_id,
            organisation_name=first["organisation_name"],
            as_of=_date(first["as_of_date"]),
            min_cohort=int(first["min_cohort_k"]),
            built_at=_ts(max(r["_built_at"] for r in rows)),
            rows=[
                OrgProgressRow(
                    course_id=r["course_id"],
                    course_title=r["course_title"],
                    skill=r["skill"],
                    cohort_size=int(r["cohort_size"]),
                    # suppression is the mart's decision: never surface a rate it nulled
                    completion_rate=None if r["is_suppressed"] else _opt(r["completion_rate"]),
                    avg_mastery=None if r["is_suppressed"] else _opt(r["avg_mastery"]),
                    completed_learners=None
                    if r["is_suppressed"] or r["completed_learners"] is None
                    else int(r["completed_learners"]),
                    suppressed=bool(r["is_suppressed"]),
                )
                for r in rows
            ],
        )

    # --- BR7 ----------------------------------------------------------------------
    def _versions(self, column: str, value: str) -> list[VideoVersion]:
        """Versions grouped per video, newest first; videos by their newest title.

        Not sorted by title in SQL: a re-cut version may be retitled, which would split the
        versions of one video or put an old version first.
        """
        rows = self._query(
            "SELECT DISTINCT content_id, content_version, content_title, course_id, duration_sec "
            f"FROM {self._t('mart.video_heatmap')} WHERE {column} = ? "
            "ORDER BY content_id, content_version DESC NULLS LAST",
            [value],
        )
        newest_title: dict[str, str] = {}
        for r in rows:
            newest_title.setdefault(r["content_id"], r["content_title"] or r["content_id"])
        rows.sort(key=lambda r: (newest_title[r["content_id"]], r["content_id"]))  # stable
        return [
            VideoVersion(
                content_id=r["content_id"],
                version=None if r["content_version"] is None else int(r["content_version"]),
                title=r["content_title"],
                course_id=r["course_id"],
                duration_sec=None if r["duration_sec"] is None else int(r["duration_sec"]),
            )
            for r in rows
        ]

    def course_videos(self, course_id: str) -> list[VideoVersion]:
        return self._versions("course_id", course_id)

    def video(self, content_id: str) -> list[VideoVersion]:
        return self._versions("content_id", content_id)

    def video_heatmap(self, content_id: str, version: int | None) -> VideoHeatmapSnapshot | None:
        versions = self.video(content_id)
        chosen = next((v for v in versions if version is None or v.version == version), None)
        if chosen is None:
            return None
        rows = self._query(
            "SELECT as_of_date, window_days, second, play_count, pause_count, seek_count, "
            f"unique_learners, intensity, _built_at FROM {self._t('mart.video_heatmap')} "
            "WHERE content_id = ? AND coalesce(content_version, -1) = ? ORDER BY second",
            [content_id, _NO_VERSION if chosen.version is None else chosen.version],
        )
        if not rows:
            return None
        return VideoHeatmapSnapshot(
            video=chosen,
            as_of=_date(rows[0]["as_of_date"]),
            window_days=int(rows[0]["window_days"]),
            built_at=_ts(max(r["_built_at"] for r in rows)),
            seconds=[
                HeatmapSecond(
                    second=int(r["second"]),
                    play=int(r["play_count"]),
                    pause=int(r["pause_count"]),
                    seek=int(r["seek_count"]),
                    learners=int(r["unique_learners"]),
                    intensity=float(r["intensity"]),
                )
                for r in rows
            ],
        )

    # --- BR8 ----------------------------------------------------------------------
    def engagement_trend(
        self, course_id: str, as_of: date | None
    ) -> EngagementTrendSnapshot | None:
        table = self._t("mart.engagement_trend")
        rows = self._query(
            "SELECT as_of_date, learner_pseudonym, week_index, week_start, engagement_score, "
            "delta_vs_previous, is_declining, course_avg_score, decline_ratio, _built_at "
            f"FROM {table} WHERE course_id = ? AND as_of_date = ("
            f"SELECT max(as_of_date) FROM {table} WHERE course_id = ? AND as_of_date <= ?) "
            "ORDER BY learner_pseudonym, week_index",
            [course_id, course_id, as_of or _LATEST],
        )
        if not rows:
            return None
        weeks: dict[int, tuple[date, float]] = {}
        series: dict[str, list[Row]] = {}
        for r in rows:
            weeks[int(r["week_index"])] = (_date(r["week_start"]), float(r["course_avg_score"]))
            series.setdefault(r["learner_pseudonym"], []).append(r)
        order = sorted(weeks)
        return EngagementTrendSnapshot(
            course_id=course_id,
            as_of=_date(rows[0]["as_of_date"]),
            week_starts=[weeks[i][0] for i in order],
            course_avg=[weeks[i][1] for i in order],
            decline_ratio=float(rows[0]["decline_ratio"]),
            built_at=_ts(max(r["_built_at"] for r in rows)),
            learners=[
                EngagementSeries(
                    learner_pseudonym=pseudonym,
                    scores=[float(r["engagement_score"]) for r in points],
                    deltas=[_opt(r["delta_vs_previous"]) for r in points],
                    declining=bool(points[-1]["is_declining"]),
                )
                for pseudonym, points in series.items()
            ],
        )


def _opt(value: Any) -> float | None:
    return None if value is None else float(value)


def _date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _ts(value: Any) -> datetime:
    """Warehouse timestamps are UTC; Spark returns them naive, Trino zoned."""
    ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)

"""BR6/BR7/BR8 serving API: authorization scopes, suppression pass-through, error mapping.

The mart reader is replaced by an in-memory fake; the reader's SQL itself is exercised
against real Delta tables in tests/integration/test_lakehouse_marts.py.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from edu_platform.br45.config import settings as br45_settings
from edu_platform.contexts.analytics.application.ports import (
    EngagementSeries,
    EngagementTrendSnapshot,
    HeatmapSecond,
    LiveEngagement,
    LiveHeatmap,
    LiveSecond,
    MartUnavailable,
    NamedRef,
    OrgProgressRow,
    OrgProgressSnapshot,
    VideoHeatmapSnapshot,
    VideoVersion,
)
from edu_platform.entrypoints.api.main import create_app
from edu_platform.entrypoints.api.routers.lakehouse import live_overlay, mart_reader, today

BUILT = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)
TOKENS = {
    "acme": {"id": "admin-acme", "role": "admin", "organisations": ["org-acme"]},
    "both": {"id": "admin-all", "role": "admin", "organisations": ["org-acme", "org-globex"]},
    "teacher": {"id": "inst-1", "role": "instructor", "courses": ["c-sql-101"]},
    "advisor": {"id": "adv-1", "role": "advisor", "courses": ["c-sql-101"]},
}


class FakeReader:
    def __init__(self) -> None:
        self.down = False
        self.calls: list[tuple[str, object]] = []

    def _check(self) -> None:
        if self.down:
            raise MartUnavailable("connection refused")

    def organisations(self, ids: list[str]) -> list[NamedRef]:
        self._check()
        names = {"org-acme": "Acme Learning", "org-globex": "Globex Academy"}
        return [NamedRef(i, names[i]) for i in ids if i in names]

    def courses(self, ids: list[str]) -> list[NamedRef]:
        self._check()
        return [NamedRef(i, "SQL Foundations") for i in ids if i == "c-sql-101"]

    def org_progress(self, organisation_id: str, as_of: date | None) -> OrgProgressSnapshot | None:
        self._check()
        self.calls.append(("org_progress", as_of))
        if organisation_id == "org-globex":
            row = OrgProgressRow("c-sql-101", "SQL Foundations", "sql", 2, None, None, None, True)
        elif organisation_id == "org-acme":
            row = OrgProgressRow("c-sql-101", "SQL Foundations", "sql", 37, 0.64, 0.652, 17, False)
        else:
            return None
        return OrgProgressSnapshot(organisation_id, None, date(2026, 10, 17), 5, BUILT, [row])

    def course_videos(self, course_id: str) -> list[VideoVersion]:
        self._check()
        return [v for v in self._all() if v.course_id == course_id]

    def video(self, content_id: str) -> list[VideoVersion]:
        self._check()
        return [v for v in self._all() if v.content_id == content_id]

    @staticmethod
    def _all() -> list[VideoVersion]:
        return [
            VideoVersion("v-sql-joins", 2, "Joins", "c-sql-101", 390),
            VideoVersion("v-sql-joins", 1, "Joins", "c-sql-101", 420),
            VideoVersion("v-py-func", 1, "Functions", "c-py-201", 300),
            VideoVersion("v-orphan", None, None, None, None),
        ]

    def video_heatmap(self, content_id: str, version: int | None) -> VideoHeatmapSnapshot | None:
        self._check()
        chosen = next(
            (v for v in self.video(content_id) if version is None or v.version == version), None
        )
        if chosen is None:
            return None
        seconds = [HeatmapSecond(s, 1, 0, s % 2, 1, 0.5) for s in range(3)]
        return VideoHeatmapSnapshot(chosen, date(2026, 10, 17), 28, BUILT, seconds)

    def engagement_trend(
        self, course_id: str, as_of: date | None
    ) -> EngagementTrendSnapshot | None:
        self._check()
        if course_id != "c-sql-101":
            return None
        weeks = [date(2026, 9, 20), date(2026, 9, 27), date(2026, 10, 4), date(2026, 10, 11)]
        return EngagementTrendSnapshot(
            course_id,
            date(2026, 10, 17),
            weeks,
            [10.0, 9.0, 8.0, 7.0],
            0.3,
            BUILT,
            [
                EngagementSeries("p1", [20.0, 12.0, 6.0, 2.0], [None, -8.0, -6.0, -4.0], True),
                EngagementSeries("p2", [5.0, 6.0, 7.0, 8.0], [None, 1.0, 1.0, 1.0], False),
            ],
        )


class FakeLive:
    def __init__(self) -> None:
        self.down = False
        self.heatmap_days: list[date] = []

    def heatmap(self, content_id: str, days: list[date]) -> LiveHeatmap:
        if self.down:
            raise ConnectionError("redis down")
        self.heatmap_days = days
        seconds = [LiveSecond(1, 2, 1, 0, 2), LiveSecond(999, 0, 0, 3, 1)]  # 999: past the end
        return LiveHeatmap(content_id, days[-1:], BUILT, seconds)

    def engagement(self, course_id: str, day: date) -> LiveEngagement:
        if self.down:
            raise ConnectionError("redis down")
        return LiveEngagement(course_id, day, BUILT, {"p1": 1.0, "p2": 4.0})


TODAY = date(2026, 10, 19)  # two days after the mart snapshot (2026-10-17)


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def live() -> FakeLive:
    return FakeLive()


@pytest.fixture
def client(
    reader: FakeReader, live: FakeLive, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("EDU_BR45_AUTH", json.dumps(TOKENS))
    br45_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[mart_reader] = lambda: reader
    app.dependency_overrides[live_overlay] = lambda: live
    app.dependency_overrides[today] = lambda: TODAY
    yield TestClient(app)  # no lifespan: the demo platform is not needed
    br45_settings.cache_clear()


def get(client: TestClient, path: str, token: str | None) -> tuple[int, dict]:  # type: ignore[type-arg]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.get(f"/api{path}", headers=headers)
    return response.status_code, response.json()


# --- authentication / session --------------------------------------------------------
def test_requires_a_valid_token(client: TestClient) -> None:
    assert get(client, "/admin/organisations/org-acme/skill-progress", None)[0] == 401
    assert get(client, "/admin/organisations/org-acme/skill-progress", "nope")[0] == 401


def test_session_names_scopes_from_dimensions(client: TestClient) -> None:
    status, body = get(client, "/lakehouse/session", "both")
    assert status == 200
    assert body["role"] == "admin"
    assert body["organisations"] == [
        {"id": "org-acme", "name": "Acme Learning"},
        {"id": "org-globex", "name": "Globex Academy"},
    ]
    assert get(client, "/lakehouse/session", "teacher")[1]["courses"] == [
        {"id": "c-sql-101", "title": "SQL Foundations"}
    ]


# --- BR6 ------------------------------------------------------------------------------
def test_admin_reads_only_own_organisations(client: TestClient) -> None:
    status, body = get(client, "/admin/organisations/org-acme/skill-progress", "acme")
    assert status == 200
    assert body["rows"][0]["completion_rate"] == 0.64
    assert body["min_cohort"] == 5
    assert get(client, "/admin/organisations/org-globex/skill-progress", "acme")[0] == 403


def test_other_roles_cannot_read_org_progress(client: TestClient) -> None:
    for token in ("teacher", "advisor"):
        assert get(client, "/admin/organisations/org-acme/skill-progress", token)[0] == 403


def test_suppressed_cohort_is_served_without_rates(client: TestClient) -> None:
    _, body = get(client, "/admin/organisations/org-globex/skill-progress", "both")
    row = body["rows"][0]
    assert row["suppressed"] is True
    assert row["cohort_size"] == 2
    assert row["completion_rate"] is None and row["avg_mastery"] is None
    assert row["completed_learners"] is None


def test_as_of_is_passed_and_validated(client: TestClient, reader: FakeReader) -> None:
    get(client, "/admin/organisations/org-acme/skill-progress?as_of=2026-10-16", "acme")
    assert reader.calls[-1] == ("org_progress", date(2026, 10, 16))
    status, _ = get(client, "/admin/organisations/org-acme/skill-progress?as_of=yesterday", "acme")
    assert status == 422


def test_missing_snapshot_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EDU_BR45_AUTH", json.dumps({"x": {"id": "x", "role": "admin", "organisations": ["o"]}})
    )
    br45_settings.cache_clear()
    assert get(client, "/admin/organisations/o/skill-progress", "x")[0] == 404


# --- BR7 ------------------------------------------------------------------------------
def test_course_videos_group_versions_newest_first(client: TestClient) -> None:
    status, body = get(client, "/instructor/courses/c-sql-101/videos", "teacher")
    assert status == 200
    assert body["videos"] == [
        {
            "content_id": "v-sql-joins",
            "title": "Joins",
            "versions": [
                {"version": 2, "duration_sec": 390},
                {"version": 1, "duration_sec": 420},
            ],
        }
    ]
    assert get(client, "/instructor/courses/c-py-201/videos", "teacher")[0] == 403


def test_heatmap_defaults_to_newest_version(client: TestClient) -> None:
    status, body = get(client, "/instructor/videos/v-sql-joins/interaction-heatmap", "teacher")
    assert status == 200
    assert body["video"]["version"] == 2
    assert [v["version"] for v in body["versions"]] == [2, 1]
    assert [s["second"] for s in body["seconds"]] == [0, 1, 2]
    _, v1 = get(client, "/instructor/videos/v-sql-joins/interaction-heatmap?version=1", "teacher")
    assert v1["video"]["duration_sec"] == 420


def test_heatmap_scope_and_not_found(client: TestClient) -> None:
    path = "/instructor/videos/{}/interaction-heatmap"
    assert get(client, path.format("v-py-func"), "teacher")[0] == 403
    assert get(client, path.format("v-orphan"), "teacher")[0] == 403  # course unknown
    assert get(client, path.format("v-missing"), "teacher")[0] == 404
    assert get(client, path.format("v-sql-joins") + "?version=9", "teacher")[0] == 404
    assert get(client, path.format("v-sql-joins"), "advisor")[0] == 403


# --- BR8 ------------------------------------------------------------------------------
def test_engagement_trend(client: TestClient) -> None:
    status, body = get(client, "/instructor/courses/c-sql-101/engagement-trend", "teacher")
    assert status == 200
    assert body["declining_count"] == 1
    assert body["week_starts"][0] == "2026-09-20"
    assert body["learners"][0]["deltas"][0] is None
    assert get(client, "/instructor/courses/c-py-201/engagement-trend", "teacher")[0] == 403


# --- availability ---------------------------------------------------------------------
def test_warehouse_outage_is_503(client: TestClient, reader: FakeReader) -> None:
    reader.down = True
    status, body = get(client, "/instructor/courses/c-sql-101/engagement-trend", "teacher")
    assert status == 503
    assert "Trino" in body["detail"]


# --- live overlays -------------------------------------------------------------------------
def test_heatmap_live_overlay_covers_days_after_the_snapshot(
    client: TestClient, live: FakeLive
) -> None:
    _, body = get(client, "/instructor/videos/v-sql-joins/interaction-heatmap", "teacher")
    assert live.heatmap_days == [date(2026, 10, 18), date(2026, 10, 19)]
    assert body["live"]["days"] == ["2026-10-19"]
    # second 999 is clamped onto the last second of the 390 s video, like the mart does
    assert body["live"]["seconds"] == [
        {"second": 1, "play": 2, "pause": 1, "seek": 0, "learners": 2},
        {"second": 389, "play": 0, "pause": 0, "seek": 3, "learners": 1},
    ]


def test_heatmap_live_only_for_the_newest_version_and_on_request(client: TestClient) -> None:
    path = "/instructor/videos/v-sql-joins/interaction-heatmap"
    assert get(client, path + "?version=1", "teacher")[1]["live"] is None
    assert get(client, path + "?live=false", "teacher")[1]["live"] is None


def test_engagement_live_today(client: TestClient) -> None:
    _, body = get(client, "/instructor/courses/c-sql-101/engagement-trend", "teacher")
    assert body["live"] == {
        "day": "2026-10-19",
        "updated_at": "2026-10-17T02:00:00Z",
        "scores": {"p1": 1.0, "p2": 4.0},
        "course_avg": 2.5,
    }
    history = get(
        client, "/instructor/courses/c-sql-101/engagement-trend?as_of=2026-10-17", "teacher"
    )
    assert history[1]["live"] is None  # a historical view never mixes in today's stream


def test_redis_outage_degrades_to_mart_only(client: TestClient, live: FakeLive) -> None:
    live.down = True
    status, heat = get(client, "/instructor/videos/v-sql-joins/interaction-heatmap", "teacher")
    assert status == 200 and heat["live"] is None and heat["seconds"]
    status, trend = get(client, "/instructor/courses/c-sql-101/engagement-trend", "teacher")
    assert status == 200 and trend["live"] is None and trend["learners"]

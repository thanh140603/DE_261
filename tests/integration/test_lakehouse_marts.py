"""TrinoMartReader SQL against real Delta tables created from warehouse/ddl.

Needs only pyspark + delta-spark + a JDK (no docker): the reader runs with ``catalog=None``
on a local Spark session, so a renamed mart column or a broken query fails here.

  uv run pytest -m spark tests/integration/test_lakehouse_marts.py
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from edu_platform.contexts.analytics.infrastructure.trino_mart_reader import TrinoMartReader
from edu_platform.platform.warehouse.sql import render, split_statements

pytestmark = pytest.mark.spark

DDL = Path(__file__).resolve().parents[2] / "warehouse" / "ddl"
TABLES = ("gold.dim_organisation", "gold.dim_course", "mart.org_progress", "mart.video_heatmap",
          "mart.engagement_trend")  # fmt: skip


@pytest.fixture(scope="module")
def spark(spark_session: Any, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    session = spark_session
    root = tmp_path_factory.mktemp("lake")
    params = {"lakehouse_root": f"file://{root}"}
    for name in ("00_schemas.sql", "30_gold_dimensions.sql", "50_marts.sql"):
        for statement in split_statements(render((DDL / name).read_text("utf-8"), params)):
            session.sql(statement)
    _seed(session)
    yield session
    for schema in ("bronze", "silver", "gold", "mart", "features", "ops"):
        session.sql(f"DROP DATABASE IF EXISTS {schema} CASCADE")


def _seed(spark: Any) -> None:
    built = "TIMESTAMP'2026-10-17 02:00:00'"
    spark.sql(f"""INSERT INTO gold.dim_organisation VALUES
        (1, 'org-acme', 'Acme Learning', 'enterprise', false, {built}),
        (2, 'org-globex', 'Globex Academy', 'team', false, {built})""")
    spark.sql(f"""INSERT INTO gold.dim_course VALUES
        (1, 'c-sql-101', 'SQL Foundations', 'sql', 'beginner', NULL, 4, false, {built}),
        (2, 'c-py-201', 'Python for Data', 'python', 'intermediate', NULL, 5, false, {built})""")
    # BR6: two snapshots for Acme; Globex is suppressed. The Globex row deliberately carries
    # a rate despite is_suppressed, to prove the reader never surfaces it.
    spark.sql(f"""INSERT INTO mart.org_progress VALUES
        (DATE'2026-10-16', 'org-acme', 'Acme Learning', 'c-sql-101', 'SQL Foundations', 'sql',
         36, 0.6, 0.65, 15, false, 5, {built}),
        (DATE'2026-10-17', 'org-acme', 'Acme Learning', 'c-sql-101', 'SQL Foundations', 'sql',
         37, 0.64, 0.652, 17, false, 5, {built}),
        (DATE'2026-10-17', 'org-acme', 'Acme Learning', 'c-py-201', 'Python for Data', 'python',
         36, 0.741, 0.701, 17, false, 5, {built}),
        (DATE'2026-10-17', 'org-globex', 'Globex Academy', 'c-sql-101', 'SQL Foundations', 'sql',
         2, 0.5, 0.5, 1, true, 5, {built})""")
    # BR7: v-sql-joins re-cut and retitled (v1 420 s "Joins", v2 390 s "Joins (re-cut)",
    # 3 seconds each here) - a title sort must not put v1 first; one inferred video.
    rows = []
    for version, plays in ((1, (3, 1, 0)), (2, (5, 0, 2))):
        title = "Joins" if version == 1 else "Joins (re-cut)"
        for second, play in enumerate(plays):
            rows.append(
                f"(DATE'2026-10-17', 28, 'v-sql-joins', {version}, '{title}', 'c-sql-101', "
                f"{420 if version == 1 else 390}, {second}, {play}, 1, 0, {play}, "
                f"{play / max(plays):.4f}, {built})"
            )
    rows.append(
        f"(DATE'2026-10-17', 28, 'v-orphan', NULL, NULL, NULL, NULL, 0, 1, 0, 0, 1, 1.0, {built})"
    )
    rows.append(
        f"(DATE'2026-10-17', 28, 'v-sql-index', 1, 'Joins and indexes', 'c-sql-101', 60, 0, "
        f"1, 0, 0, 1, 1.0, {built})"
    )
    spark.sql(f"INSERT INTO mart.video_heatmap VALUES {', '.join(rows)}")
    # BR8: one declining learner, one steady; weeks 1..4 ending 2026-10-17.
    trend = []
    starts = ("2026-09-20", "2026-09-27", "2026-10-04", "2026-10-11")
    series = {"p-decline": (20.0, 12.0, 6.0, 2.0), "p-steady": (5.0, 6.0, 7.0, 8.0)}
    for learner, scores in series.items():
        for i, score in enumerate(scores):
            delta = "NULL" if i == 0 else str(score - scores[i - 1])
            declining = "true" if learner == "p-decline" else "false"
            avg = (series["p-decline"][i] + series["p-steady"][i]) / 2
            trend.append(
                f"(DATE'2026-10-17', 'c-sql-101', '{learner}', {i + 1}, DATE'{starts[i]}', "
                f"{score}, {delta}, {declining}, {avg}, 0.3, {built})"
            )
    spark.sql(f"INSERT INTO mart.engagement_trend VALUES {', '.join(trend)}")


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, date):
        return f"DATE'{value.isoformat()}'"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _inline(sql: str, params: list[Any]) -> str:
    """Bind ``?`` positionally. delta-spark 4.x leaves parameters unbound on Delta relations
    (UNBOUND_SQL_PARAMETER), so the test binds them as literals; Trino binds them natively."""
    parts = sql.split("?")
    assert len(parts) == len(params) + 1, "placeholder / parameter count mismatch"
    return parts[0] + "".join(_literal(p) + rest for p, rest in zip(params, parts[1:], strict=True))


@pytest.fixture(scope="module")
def reader(spark: Any) -> TrinoMartReader:
    def query(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        return [r.asDict() for r in spark.sql(_inline(sql, params)).collect()]

    return TrinoMartReader(query, catalog=None)


def test_reference_names(reader: TrinoMartReader) -> None:
    assert [o.name for o in reader.organisations(["org-globex", "org-acme"])] == [
        "Acme Learning",
        "Globex Academy",
    ]
    assert [c.id for c in reader.courses(["c-sql-101", "c-unknown"])] == ["c-sql-101"]
    assert reader.courses([]) == []


def test_org_progress_latest_and_as_of(reader: TrinoMartReader) -> None:
    latest = reader.org_progress("org-acme", None)
    assert latest is not None
    assert latest.as_of == date(2026, 10, 17)
    assert [r.course_id for r in latest.rows] == ["c-py-201", "c-sql-101"]  # by title
    assert latest.organisation_name == "Acme Learning"
    assert latest.built_at.tzinfo is not None

    earlier = reader.org_progress("org-acme", date(2026, 10, 16))
    assert earlier is not None and earlier.as_of == date(2026, 10, 16)
    assert earlier.rows[0].completion_rate == 0.6
    assert reader.org_progress("org-acme", date(2026, 10, 1)) is None
    assert reader.org_progress("org-unknown", None) is None


def test_suppressed_rates_never_leave_the_reader(reader: TrinoMartReader) -> None:
    snapshot = reader.org_progress("org-globex", None)
    assert snapshot is not None
    (row,) = snapshot.rows
    assert row.suppressed and row.cohort_size == 2
    assert row.completion_rate is None and row.avg_mastery is None
    assert row.completed_learners is None
    assert snapshot.min_cohort == 5


def test_video_versions_and_heatmap(reader: TrinoMartReader) -> None:
    versions = reader.course_videos("c-sql-101")
    # grouped per video, newest version first, videos ordered by their newest title
    # (a plain title sort would give joins v1 "Joins", joins v2 "Joins (re-cut)", index)
    assert [(v.content_id, v.version, v.duration_sec) for v in versions] == [
        ("v-sql-joins", 2, 390),
        ("v-sql-joins", 1, 420),
        ("v-sql-index", 1, 60),
    ]
    assert [v.version for v in reader.video("v-sql-joins")] == [2, 1]
    newest = reader.video_heatmap("v-sql-joins", None)
    assert newest is not None and newest.video.version == 2
    assert [s.play for s in newest.seconds] == [5, 0, 2]
    assert newest.window_days == 28
    v1 = reader.video_heatmap("v-sql-joins", 1)
    assert v1 is not None and [s.play for s in v1.seconds] == [3, 1, 0]
    assert reader.video_heatmap("v-sql-joins", 7) is None


def test_inferred_video_without_version(reader: TrinoMartReader) -> None:
    (orphan,) = reader.video("v-orphan")
    assert orphan.version is None and orphan.course_id is None
    heatmap = reader.video_heatmap("v-orphan", None)
    assert heatmap is not None and len(heatmap.seconds) == 1


def test_engagement_trend(reader: TrinoMartReader) -> None:
    trend = reader.engagement_trend("c-sql-101", None)
    assert trend is not None
    assert trend.week_starts == [date(2026, 9, 20), date(2026, 9, 27), date(2026, 10, 4),
                                 date(2026, 10, 11)]  # fmt: skip
    assert trend.course_avg == [12.5, 9.0, 6.5, 5.0]
    by_learner = {s.learner_pseudonym: s for s in trend.learners}
    assert by_learner["p-decline"].declining and not by_learner["p-steady"].declining
    assert by_learner["p-decline"].scores == [20.0, 12.0, 6.0, 2.0]
    assert by_learner["p-decline"].deltas[0] is None
    assert trend.decline_ratio == 0.3
    assert reader.engagement_trend("c-py-201", None) is None

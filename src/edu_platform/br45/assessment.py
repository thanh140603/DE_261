"""BR4: SQL aggregation over CDC-cleaned rows, plus an independent Python baseline."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median
from typing import Any

from psycopg.types.json import Jsonb

from .config import AnalyticsSettings, settings
from .contracts import identity
from .db import Db, state

# A submission's required test manifest is the latest version existing at submission time.
# A missing/skipped/invalid test makes the whole question attempt invalid, never a failure.
ATTEMPTS_SQL = """
WITH s AS (
 SELECT data FROM analytics.clean_rows WHERE table_name='submissions' AND NOT deleted
 AND (data->>'submitted_at')::timestamptz >= %(start)s
 AND (data->>'submitted_at')::timestamptz < %(end)s
 AND (%(course)s::text IS NULL OR data->>'course_id'=%(course)s)
), q AS (SELECT data FROM analytics.clean_rows WHERE table_name='questions' AND NOT deleted),
a AS (SELECT data FROM analytics.clean_rows WHERE table_name='assignments' AND NOT deleted),
t AS (SELECT data FROM analytics.clean_rows WHERE table_name='test_cases' AND NOT deleted),
e AS (SELECT data FROM analytics.clean_rows WHERE table_name='evaluations' AND NOT deleted)
SELECT s.data->>'id' submission_id,s.data->>'student_id' student_id,
 s.data->>'course_id' course_id,s.data->>'assignment_id' assignment_id,
 s.data->>'question_id' question_id,(s.data->>'question_version')::int question_version,
 s.data->>'submitted_at' submitted_at,s.data->>'execution_status' execution_status,
 q.data->>'title' question_title,a.data->>'title' assignment_title,
 tc.data->>'id' test_case_id,(tc.data->>'version')::int test_case_version,
 ev.data->>'status' status,
 coalesce((ev.data->>'is_valid_evaluation')::boolean,false)
 AND ev.data->>'status' IN ('passed','failed','error','timeout')
 AND s.data->>'execution_status'='evaluated' valid,
 (s.data->>'execution_status'='infra_error' OR ev.data->>'status'='infra_error') infra_error
FROM s JOIN q ON q.data->>'id'=s.data->>'question_id'
 AND q.data->>'version'=s.data->>'question_version'
JOIN a ON a.data->>'id'=s.data->>'assignment_id'
 AND q.data->>'assignment_id'=a.data->>'id'
 AND a.data->>'course_id'=s.data->>'course_id'
LEFT JOIN LATERAL (
 SELECT DISTINCT ON(data->>'id') data FROM t
 WHERE data->>'question_id'=s.data->>'question_id'
 AND data->>'question_version'=s.data->>'question_version'
 AND (data->>'created_at')::timestamptz <= (s.data->>'submitted_at')::timestamptz
 ORDER BY data->>'id',(data->>'version')::int DESC
) tc ON (tc.data->>'required')::boolean
LEFT JOIN e ev ON ev.data->>'submission_id'=s.data->>'id'
 AND ev.data->>'test_case_id'=tc.data->>'id'
 AND ev.data->>'test_case_version'=tc.data->>'version'
 AND (ev.data->>'evaluated_at')::timestamptz < %(end)s
"""

QUESTION_SQL = (
    """
WITH rows AS ("""
    + ATTEMPTS_SQL
    + """), attempts AS (
 SELECT course_id,assignment_id,question_id,question_version,question_title,assignment_title,
 submission_id,student_id,submitted_at,
 bool_and(coalesce(valid,false)) AND count(test_case_id)>0 valid,
 bool_and(status='passed') passed, bool_or(coalesce(infra_error,false)) infra_error
 FROM rows GROUP BY course_id,assignment_id,question_id,question_version,question_title,
 assignment_title,submission_id,student_id,submitted_at
), ordered AS (
 SELECT *,row_number() OVER(PARTITION BY question_id,question_version,student_id,valid
 ORDER BY submitted_at,submission_id) first_n,
 row_number() OVER(PARTITION BY question_id,question_version,student_id,valid
 ORDER BY submitted_at DESC,submission_id DESC) last_n FROM attempts
)
SELECT course_id,assignment_id,question_id,question_version,question_title,assignment_title,
 count(*) FILTER(WHERE valid)::int total_valid_evaluations,
 count(*) FILTER(WHERE valid AND passed)::int passed_evaluations,
 count(*) FILTER(WHERE valid AND NOT passed)::int failed_evaluations,
 count(DISTINCT student_id) FILTER(WHERE valid)::int unique_students,
 count(*) FILTER(WHERE NOT valid)::int invalid_evaluations,
 count(*) FILTER(WHERE infra_error)::int infrastructure_errors,
 count(*) FILTER(WHERE valid AND first_n=1)::int first_attempts,
 count(*) FILTER(WHERE valid AND first_n=1 AND passed)::int first_passes,
 count(*) FILTER(WHERE valid AND last_n=1)::int latest_attempts,
 count(*) FILTER(WHERE valid AND last_n=1 AND passed)::int latest_passes
FROM ordered
GROUP BY course_id,assignment_id,question_id,question_version,question_title,assignment_title
"""
)

CASES_SQL = (
    """
WITH rows AS ("""
    + ATTEMPTS_SQL
    + """)
SELECT course_id,assignment_id,question_id,question_version,test_case_id,test_case_version,
 count(*) FILTER(WHERE valid)::int total_valid_evaluations,
 count(*) FILTER(WHERE valid AND status='passed')::int passed_evaluations,
 count(*) FILTER(WHERE valid AND status<>'passed')::int failed_evaluations,
 count(DISTINCT student_id) FILTER(WHERE valid)::int unique_students,
 count(*) FILTER(WHERE NOT coalesce(valid,false))::int invalid_evaluations,
 count(*) FILTER(WHERE infra_error)::int infrastructure_errors
FROM rows WHERE test_case_id IS NOT NULL
GROUP BY course_id,assignment_id,question_id,question_version,test_case_id,test_case_version
"""
)


def rate(passed: int, total: int) -> float | None:
    return passed / total if total else None


def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for r in rows:
        r["pass_rate"] = rate(r["passed_evaluations"], r["total_valid_evaluations"])
        for prefix in ("first", "latest"):
            if f"{prefix}_passes" in r:
                r[f"{prefix}_attempt_pass_rate"] = rate(
                    r[f"{prefix}_passes"], r[f"{prefix}_attempts"]
                )
    return rows


def python_baseline(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Independent aggregation of validated joined evaluation facts (benchmark/parity oracle)."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[
            tuple(row[k] for k in ("course_id", "assignment_id", "question_id", "question_version"))
        ].append(row)
    questions, cases = [], []
    for key, facts in groups.items():
        base = dict(
            zip(("course_id", "assignment_id", "question_id", "question_version"), key, strict=True)
        )
        by_sub: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_case: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
        for r in facts:
            by_sub[r["submission_id"]].append(r)
            if r["test_case_id"] is not None:
                by_case[(r["test_case_id"], r["test_case_version"])].append(r)
        valid = [
            rs
            for rs in by_sub.values()
            if all(r["valid"] for r in rs) and rs[0]["test_case_id"] is not None
        ]
        students: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
        for rs in valid:
            students[rs[0]["student_id"]].append(rs)
        for attempts in students.values():
            attempts.sort(key=lambda rs: (rs[0]["submitted_at"], rs[0]["submission_id"]))

        def passed(rs: Any) -> Any:
            return all(r["status"] == "passed" for r in rs)

        questions.append(
            {
                **base,
                "question_title": facts[0]["question_title"],
                "assignment_title": facts[0]["assignment_title"],
                "total_valid_evaluations": len(valid),
                "passed_evaluations": sum(passed(rs) for rs in valid),
                "failed_evaluations": sum(not passed(rs) for rs in valid),
                "unique_students": len(students),
                "invalid_evaluations": len(by_sub) - len(valid),
                "infrastructure_errors": sum(
                    any(r["infra_error"] for r in rs) for rs in by_sub.values()
                ),
                "first_attempts": len(students),
                "latest_attempts": len(students),
                "first_passes": sum(passed(rs[0]) for rs in students.values()),
                "latest_passes": sum(passed(rs[-1]) for rs in students.values()),
            }
        )
        for (cid, version), rs in by_case.items():
            vr = [r for r in rs if r["valid"]]
            passes = sum(r["status"] == "passed" for r in vr)
            cases.append(
                {
                    **base,
                    "test_case_id": cid,
                    "test_case_version": version,
                    "total_valid_evaluations": len(vr),
                    "passed_evaluations": passes,
                    "failed_evaluations": len(vr) - passes,
                    "unique_students": len({r["student_id"] for r in vr}),
                    "invalid_evaluations": len(rs) - len(vr),
                    "infrastructure_errors": sum(bool(r["infra_error"]) for r in rs),
                }
            )
    return enrich(questions), enrich(cases)


def classify(
    row: dict[str, Any],
    peers: list[dict[str, Any]],
    previous: dict[str, Any] | None,
    cfg: AnalyticsSettings,
) -> dict[str, Any]:
    case = "test_case_id" in row
    threshold = cfg.case_threshold if case else cfg.question_threshold
    reasons: list[str] = []
    state = "NORMAL"
    if row["unique_students"] < cfg.min_students:
        state = "INSUFFICIENT_DATA"
        reasons.append(
            f"{row['unique_students']} evaluated students; at least {cfg.min_students} required"
        )
    else:
        value = row["pass_rate"]
        if value is not None and value < threshold:
            state = "LOW_PASS_RATE"
            reasons.append(f"Pass rate {value:.1%} below {threshold:.1%}")
        comparable = [
            p["pass_rate"]
            for p in peers
            if p is not row
            and p["pass_rate"] is not None
            and p["unique_students"] >= cfg.min_students
        ]
        if case and comparable and value is not None and median(comparable) - value >= cfg.peer_gap:
            state = "SUSPICIOUS_TEST_CASE"
            reasons.append(
                "Pass rate is "
                f"{median(comparable) - value:.1%}"
                " below the median of other required tests"
            )
        if (
            previous
            and previous["unique_students"] >= cfg.min_students
            and previous["pass_rate"] is not None
            and value is not None
            and previous["pass_rate"] - value >= cfg.drop_threshold
        ):
            if state == "NORMAL":
                state = "NEEDS_REVIEW"
            reasons.append(
                "Pass rate decreased by "
                f"{previous['pass_rate'] - value:.1%}"
                " from the preceding equal window"
            )
    return {
        "state": state,
        "severity": "HIGH"
        if state == "SUSPICIOUS_TEST_CASE"
        else "MEDIUM"
        if state in {"LOW_PASS_RATE", "NEEDS_REVIEW"}
        else "INFO",
        "reasons": reasons,
        "threshold": threshold,
        "minimum_students": cfg.min_students,
        "peer_gap_threshold": cfg.peer_gap,
        "drop_threshold": cfg.drop_threshold,
        "previous_pass_rate": previous["pass_rate"] if previous else None,
    }


def refresh(
    conn: Db,
    start: datetime,
    end: datetime,
    course_id: str | None = None,
    cfg: AnalyticsSettings | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = cfg or settings()
    source_revision = state(conn, "assessment_source_revision")
    revision = (
        identity(source_revision, cfg.model_dump(exclude={"auth", "dsn"}))
        if source_revision
        else None
    )
    materialization_id = identity(course_id, start.isoformat(), end.isoformat())
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (materialization_id,))
    cached = conn.execute(
        "SELECT source_revision FROM analytics.assessment_materializations WHERE id=%s",
        (materialization_id,),
    ).fetchone()
    if revision and cached and cached["source_revision"] == revision:

        def stored(table: str) -> list[dict[str, Any]]:
            return [
                r["data"]
                for r in conn.execute(
                    (
                        "SELECT data FROM analytics."
                        f"{table}"
                        " WHERE window_start=%s AND window_end=%s AND (%s::text IS NULL OR "
                        "course_id=%s) ORDER BY id"
                    ),
                    (start, end, course_id, course_id),
                )
            ]

        return stored("mart_question_pass_statistics"), stored("mart_test_case_pass_statistics")
    params = {"start": start, "end": end, "course": course_id}
    qs = enrich(list(conn.execute(QUESTION_SQL, params)))
    ts = enrich(list(conn.execute(CASES_SQL, params)))
    prev_params = {**params, "start": start - (end - start), "end": start}
    previous = enrich(list(conn.execute(QUESTION_SQL, prev_params))) + enrich(
        list(conn.execute(CASES_SQL, prev_params))
    )

    def key(r: Any) -> Any:
        return (
            r["question_id"],
            r["question_version"],
            r.get("test_case_id"),
            r.get("test_case_version"),
        )

    prev = {key(r): r for r in previous}
    # Atomic replacement also removes statistics for corrected/deleted source rows.
    for table in (
        "mart_question_pass_statistics",
        "mart_test_case_pass_statistics",
        "mart_question_anomalies",
    ):
        conn.execute(
            (
                "DELETE FROM analytics."
                f"{table}"
                " WHERE window_start=%s AND window_end=%s AND (%s::text IS NULL OR "
                "course_id=%s)"
            ),
            (start, end, course_id, course_id),
        )
    for r in qs + ts:
        peers = [
            t
            for t in ts
            if t["question_id"] == r["question_id"]
            and t["question_version"] == r["question_version"]
        ]
        r.update(classify(r, peers, prev.get(key(r)), cfg))
        r.update(
            window_start=start.isoformat(),
            window_end=end.isoformat(),
            computed_at=datetime.now(end.tzinfo).isoformat(),
        )
        r["id"] = identity(key(r), start.isoformat(), end.isoformat())
        case = "test_case_id" in r
        cols = (
            ["id", "course_id", "assignment_id", "question_id", "question_version"]
            + (["test_case_id", "test_case_version"] if case else [])
            + ["window_start", "window_end"]
        )
        table = "mart_test_case_pass_statistics" if case else "mart_question_pass_statistics"
        conn.execute(
            (
                "INSERT INTO analytics."
                f"{table}"
                "("
                f"{','.join(cols)}"
                ",data) VALUES("
                f"{','.join(['%s'] * (len(cols) + 1))}"
                ")"
            ),
            (*[r[c] for c in cols], Jsonb(r)),
        )
        if r["state"] not in {"NORMAL", "INSUFFICIENT_DATA"}:
            conn.execute(
                (
                    "INSERT INTO analytics.mart_question_anomalies(id,course_id,assignment_id,que"
                    "stion_id,state,severity,window_start,window_end,data) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                ),
                (
                    r["id"],
                    r["course_id"],
                    r["assignment_id"],
                    r["question_id"],
                    r["state"],
                    r["severity"],
                    start,
                    end,
                    Jsonb(r),
                ),
            )
    if revision:
        conn.execute(
            (
                "INSERT INTO analytics.assessment_materializations(id,source_revision) "
                "VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET "
                "source_revision=excluded.source_revision,computed_at=now()"
            ),
            (materialization_id, revision),
        )
    return qs, ts

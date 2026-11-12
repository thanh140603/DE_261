"""PostgreSQL/API correctness. Every test rolls back its isolated analytical changes."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from edu_platform.br45.api import database, router
from edu_platform.br45.assessment import (
    ATTEMPTS_SQL,
    CASES_SQL,
    QUESTION_SQL,
    enrich,
    python_baseline,
    refresh,
)
from edu_platform.br45.cdc import ingest
from edu_platform.br45.config import AnalyticsSettings, settings
from edu_platform.br45.db import migrate, state
from edu_platform.br45.demo_dataset import apply as apply_demo_stage
from edu_platform.br45.demo_dataset import build as build_demo_dataset
from edu_platform.br45.risk import persist
from tests.unit.test_br45 import risk

pytestmark = pytest.mark.integration
T = datetime(2026, 10, 16, 12, tzinfo=UTC)
DSN = os.getenv("EDU_BR45_TEST_DSN")


@pytest.fixture
def conn():
    if not DSN:
        pytest.skip("Set EDU_BR45_TEST_DSN to an isolated PostgreSQL database")
    migrate(DSN)
    with psycopg.connect(DSN, row_factory=dict_row) as connection:
        for table in (
            "clean_rows",
            "raw_changes",
            "quarantine",
            "outbox",
            "pipeline_state",
            "risk_state",
            "risk_history",
            "intervention_notes",
            "dropout_alerts",
            "course_policies",
            "assessment_jobs",
            "domain_outbox",
            "risk_dirty",
            "activity_windows",
            "mart_question_pass_statistics",
            "mart_test_case_pass_statistics",
            "mart_question_anomalies",
        ):
            connection.execute(f"DELETE FROM analytics.{table}")
        yield connection
        connection.rollback()


def load(conn, table, row, lsn=None, op="c", before=None):
    if lsn is None:
        lsn = conn.execute("SELECT count(*)+1 n FROM analytics.raw_changes").fetchone()["n"]
    return ingest(
        conn,
        "test." + table,
        0,
        lsn,
        {
            "op": op,
            "source": {"table": table, "lsn": lsn, "txId": 1},
            "after": row if op != "d" else None,
            "before": before or (row if op == "d" else None),
        },
    )


def source(conn, n=24):
    created = (T - timedelta(days=40)).isoformat()
    load(
        conn,
        "courses",
        {"id": "c", "title": "Synthetic", "telemetry_enabled": True, "created_at": created},
    )
    load(
        conn,
        "assignments",
        {
            "id": "a",
            "course_id": "c",
            "title": "A",
            "deadline": None,
            "required": True,
            "published_at": created,
        },
    )
    load(
        conn,
        "questions",
        {"id": "q", "version": 1, "assignment_id": "a", "title": "Q", "created_at": created},
    )
    for case in ("t1", "t2", "t3"):
        load(
            conn,
            "test_cases",
            {
                "id": case,
                "version": 1,
                "question_id": "q",
                "question_version": 1,
                "required": True,
                "created_at": created,
            },
        )
    for i in range(n):
        add_attempt(conn, str(i), f"s{i}", i < 2)


def add_attempt(conn, sub, student, passes, version=1, submitted=None):
    submitted = submitted or T - timedelta(days=1)
    load(
        conn,
        "submissions",
        {
            "id": sub,
            "student_id": student,
            "course_id": "c",
            "assignment_id": "a",
            "question_id": "q",
            "question_version": version,
            "execution_status": "evaluated",
            "submitted_at": submitted.isoformat(),
        },
    )
    for case in ("t1", "t2", "t3"):
        load(
            conn,
            "evaluations",
            {
                "id": f"{sub}-{case}",
                "submission_id": sub,
                "test_case_id": case,
                "test_case_version": version,
                "status": "passed" if passes or case != "t2" else "failed",
                "is_valid_evaluation": True,
                "evaluated_at": (submitted + timedelta(seconds=1)).isoformat(),
            },
        )


def results(conn):
    return refresh(conn, T - timedelta(days=30), T, "c")


def test_workflow_sql_python_parity_retry_and_correction(conn):
    source(conn)
    q, t = results(conn)
    assert q[0]["pass_rate"] == 2 / 24
    assert q[0]["unique_students"] == 24
    assert next(r for r in t if r["test_case_id"] == "t2")["state"] == "SUSPICIOUS_TEST_CASE"
    params = {"start": T - timedelta(days=30), "end": T, "course": "c"}
    pq, pt = python_baseline(list(conn.execute(ATTEMPTS_SQL, params)))
    assert pq == enrich(list(conn.execute(QUESTION_SQL, params)))
    assert sorted(pt, key=lambda r: r["test_case_id"]) == sorted(
        enrich(list(conn.execute(CASES_SQL, params))), key=lambda r: r["test_case_id"]
    )
    add_attempt(conn, "retry", "s2", True, submitted=T - timedelta(hours=2))
    q, _ = results(conn)
    assert q[0]["total_valid_evaluations"] == 25
    assert q[0]["first_attempt_pass_rate"] == 2 / 24
    assert q[0]["latest_attempt_pass_rate"] == 3 / 24
    row = conn.execute(
        "SELECT data FROM analytics.clean_rows WHERE table_name='evaluations' AND row_key='3-t2'"
    ).fetchone()["data"]
    load(conn, "evaluations", {**row, "status": "passed"}, op="u", before=row)
    assert results(conn)[0][0]["passed_evaluations"] == 4


@pytest.mark.parametrize(
    "status,valid,expected_valid,infra",
    [
        ("passed", True, 1, 0),
        ("failed", True, 1, 0),
        ("error", True, 1, 0),
        ("timeout", True, 1, 0),
        ("skipped", True, 0, 0),
        ("infra_error", False, 0, 1),
    ],
)
def test_evaluation_semantics(conn, status, valid, expected_valid, infra):
    source(conn, 1)
    row = conn.execute(
        "SELECT data FROM analytics.clean_rows WHERE table_name='evaluations' AND row_key='0-t2'"
    ).fetchone()["data"]
    load(
        conn,
        "evaluations",
        {**row, "status": status, "is_valid_evaluation": valid},
        op="u",
        before=row,
    )
    q, _ = results(conn)
    assert q[0]["total_valid_evaluations"] == expected_valid
    assert q[0]["infrastructure_errors"] == infra
    assert q[0]["state"] == "INSUFFICIENT_DATA"


def test_duplicate_out_of_order_update_delete_quarantine_and_lateness(conn):
    row = {
        "id": "e",
        "student_id": "s",
        "course_id": "c",
        "event_type": "lesson_view",
        "event_time": (T - timedelta(days=1)).isoformat(),
    }
    assert load(conn, "activity_events", row, 10) == "processed"
    assert load(conn, "activity_events", row, 10) == "duplicate"
    assert load(conn, "activity_events", row, 9) == "stale"
    changed = {**row, "event_time": (T - timedelta(days=2)).isoformat()}
    assert load(conn, "activity_events", changed, 11, "u", row) == "processed"
    assert load(conn, "activity_events", changed, 12, "d") == "processed"
    assert (
        conn.execute("SELECT sum((payload->>'delta')::int) n FROM analytics.outbox").fetchone()["n"]
        == 0
    )
    assert (
        load(conn, "activity_events", {**row, "id": "bad", "event_time": "naive"}, 13) == "invalid"
    )
    from edu_platform.br45.db import state

    state(conn, "stream_watermark", (T - timedelta(days=21)).isoformat())
    assert (
        load(
            conn,
            "activity_events",
            {**row, "id": "too-late", "event_time": (T - timedelta(days=22)).isoformat()},
            14,
        )
        == "invalid"
    )
    assert (
        load(
            conn,
            "activity_events",
            {**row, "id": "late", "event_time": (T - timedelta(days=20)).isoformat()},
            15,
        )
        == "processed"
    )


def test_missing_results_versions_and_all_pass_fail(conn):
    source(conn, 2)
    q, _ = results(conn)
    assert q[0]["pass_rate"] == 1
    missing = conn.execute(
        "SELECT data FROM analytics.clean_rows WHERE table_name='evaluations' AND row_key='1-t1'"
    ).fetchone()["data"]
    load(conn, "evaluations", missing, op="d")
    q, _ = results(conn)
    assert q[0]["total_valid_evaluations"] == 1 and q[0]["invalid_evaluations"] == 1
    created = (T - timedelta(days=30)).isoformat()
    load(
        conn,
        "questions",
        {"id": "q", "version": 2, "assignment_id": "a", "title": "Q v2", "created_at": created},
    )
    for case in ("t1", "t2", "t3"):
        load(
            conn,
            "test_cases",
            {
                "id": case,
                "version": 2,
                "question_id": "q",
                "question_version": 2,
                "required": True,
                "created_at": created,
            },
        )
    add_attempt(conn, "v2", "student2", False, version=2)
    qs, ts = results(conn)
    assert {q["question_version"] for q in qs} == {1, 2}
    assert next(q for q in qs if q["question_version"] == 2)["pass_rate"] == 0
    assert len(ts) == 6


def test_scoped_api_alert_lifecycle_and_idempotent_history(conn, monkeypatch):
    monkeypatch.setenv(
        "EDU_BR45_AUTH",
        json.dumps(
            {
                "i": {"id": "teacher", "role": "instructor", "courses": ["c"]},
                "a": {"id": "advisor", "role": "advisor", "courses": ["c"]},
                "outside": {"id": "other", "role": "advisor", "courses": ["other"]},
            }
        ),
    )
    settings.cache_clear()

    source(conn)
    result = risk()
    # V2 GET reads a published generation; it must not run an aggregation itself.
    from edu_platform.br45.db import state
    state(conn, "evaluation_clock", T.isoformat())
    results(conn)
    for _ in range(3):
        persist(conn, result)
    assert conn.execute("SELECT count(*) n FROM analytics.dropout_alerts").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) n FROM analytics.risk_history").fetchone()["n"] == 1
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[database] = lambda: conn
    with TestClient(app) as client:
        assert client.get("/api/advisor/alerts").status_code == 401
        assert (
            client.get("/api/advisor/alerts", headers={"Authorization": "Bearer i"}).status_code
            == 403
        )
        assert (
            client.get("/api/advisor/alerts", headers={"Authorization": "Bearer outside"}).json()[
                "total"
            ]
            == 0
        )
        auth = {"Authorization": "Bearer a"}
        alert = client.get("/api/advisor/alerts", headers=auth).json()["items"][0]
        aid = alert["id"]
        assert (
            client.patch(f"/api/advisor/alerts/{aid}/acknowledge", headers=auth).json()["status"]
            == "ACKNOWLEDGED"
        )
        acknowledged = client.patch(f"/api/advisor/alerts/{aid}/acknowledge", headers=auth).json()[
            "acknowledged_at"
        ]
        assert acknowledged
        assert (
            client.patch(f"/api/advisor/alerts/{aid}/resolve", headers=auth).json()["status"]
            == "RESOLVED"
        )
        assert (
            client.patch(f"/api/advisor/alerts/{aid}/acknowledge", headers=auth).status_code == 409
        )
        assert (
            client.get(
                "/api/advisor/students/s/risk", headers={"Authorization": "Bearer outside"}
            ).status_code
            == 404
        )
        data = client.get(
            "/api/instructor/courses/c/questions/statistics", headers={"Authorization": "Bearer i"}
        ).json()
        assert data["items"][0]["pass_rate"] == 2 / 24
        assert (
            client.get(
                "/api/instructor/courses/c/questions/statistics?limit=0",
                headers={"Authorization": "Bearer i"},
            ).status_code
            == 422
        )
    persist(conn, result)
    assert conn.execute("SELECT count(*) n FROM analytics.dropout_alerts").fetchone()["n"] == 1
    settings.cache_clear()


def test_cooldown_transition_and_severity_history(conn):
    result = risk()
    cfg = AnalyticsSettings(cooldown_hours=72)
    persist(conn, result, cfg)
    recovered = {
        **result,
        "score": 0,
        "level": "LOW",
        "reasons": [],
        "evaluated_at": (T + timedelta(hours=1)).isoformat(),
    }
    persist(conn, recovered, cfg)
    assert (
        conn.execute("SELECT resolved_by FROM analytics.dropout_alerts").fetchone()["resolved_by"]
        == "system:risk-recovery"
    )
    persist(conn, {**result, "evaluated_at": (T + timedelta(hours=2)).isoformat()}, cfg)
    assert conn.execute("SELECT count(*) n FROM analytics.dropout_alerts").fetchone()["n"] == 1
    persist(conn, {**recovered, "evaluated_at": (T + timedelta(days=4)).isoformat()}, cfg)
    persist(conn, {**result, "evaluated_at": (T + timedelta(days=4, hours=1)).isoformat()}, cfg)
    assert conn.execute("SELECT count(*) n FROM analytics.dropout_alerts").fetchone()["n"] == 2


def test_unique_students_sample_guard(conn):
    source(conn, 1)
    for i in range(20):
        add_attempt(conn, f"retry-{i}", "s0", False, submitted=T - timedelta(hours=1, minutes=i))
    q, _ = results(conn)
    assert q[0]["unique_students"] == 1 and q[0]["total_valid_evaluations"] == 21
    assert q[0]["state"] == "INSUFFICIENT_DATA"


def test_same_question_test_version_manifest(conn):
    source(conn, 1)
    created = (T - timedelta(hours=12)).isoformat()
    load(
        conn,
        "test_cases",
        {
            "id": "t1",
            "version": 2,
            "question_id": "q",
            "question_version": 1,
            "required": True,
            "created_at": created,
        },
    )
    add_attempt(conn, "new-manifest", "s-new", True, submitted=T - timedelta(hours=1))
    ev = conn.execute(
        "SELECT data FROM analytics.clean_rows WHERE table_name='evaluations' "
        "AND row_key='new-manifest-t1'"
    ).fetchone()["data"]
    load(conn, "evaluations", {**ev, "test_case_version": 2}, op="u", before=ev)
    q, ts = results(conn)
    assert q[0]["total_valid_evaluations"] == 2 and q[0]["pass_rate"] == 1
    assert {(t["test_case_id"], t["test_case_version"]) for t in ts} == {
        ("t1", 1),
        ("t1", 2),
        ("t2", 1),
        ("t3", 1),
    }


def test_demo_stage_retries_preserve_regrade_and_respect_watermark(conn):
    dataset = build_demo_dataset("integration-test", T)
    course = dataset["course_id"]
    state(conn, "stream_watermark", (T - timedelta(days=10)).isoformat())
    with pytest.raises(ValueError, match="Spark watermark"):
        apply_demo_stage(conn, dataset, "baseline")
    assert not conn.execute("SELECT 1 FROM br45.courses WHERE id=%s", (course,)).fetchone()

    state(conn, "stream_watermark", (T - timedelta(days=21)).isoformat())
    assert apply_demo_stage(conn, dataset, "baseline")
    with pytest.raises(ValueError, match="Evaluation clock"):
        apply_demo_stage(conn, dataset, "regrade")
    state(conn, "evaluation_clock", T.isoformat())
    assert apply_demo_stage(conn, dataset, "regrade")
    assert not apply_demo_stage(conn, dataset, "regrade")
    assert not apply_demo_stage(conn, dataset, "baseline")

    case = f"{course}-case-empty-input"
    counts = {
        row["status"]: row["n"]
        for row in conn.execute(
            "SELECT status, count(*) n FROM br45.evaluations WHERE test_case_id=%s GROUP BY status",
            (case,),
        )
    }
    assert counts == {"passed": 22, "failed": 2}


def test_job_lease_fences_expired_worker_and_requeues_new_revision(conn):
    from edu_platform.br45 import jobs

    start = T - timedelta(days=30)
    cfg = AnalyticsSettings(assessment_engine="spark")
    state(conn, "assessment_source_revision", "first")
    state(conn, "assessment_sequence", 12)
    job = jobs.request(conn, "c", start, T, cfg)
    assert jobs.pending(conn, "spark", 11) is None
    old = jobs.pending(conn, "spark", 12)
    assert old and jobs.owns_lease(conn, old)
    conn.execute(
        "UPDATE analytics.assessment_jobs SET started_at=now()-interval '31 minutes' WHERE id=%s",
        (job["id"],),
    )
    new = jobs.pending(conn, "spark", 12)
    assert new and new["lease_generation"] > old["lease_generation"]
    assert not jobs.owns_lease(conn, old)
    jobs.fail(conn, old, RuntimeError("stale worker"))
    assert jobs.owns_lease(conn, new)

    state(conn, "assessment_source_revision", "second")
    state(conn, "assessment_sequence", 20)
    jobs.request(conn, "c", start, T, cfg)
    jobs.complete(conn, new, "first", "publication-1", 7)
    pending = jobs.request(conn, "c", start, T, cfg)
    assert pending["status"] == "PENDING"
    assert pending["published_revision"] == "first"
    assert pending["requested_revision"] == "second"
    assert pending["source_delta_version"] == 7
    assert jobs.pending(conn, "spark", 19) is None


def test_policy_version_and_note_idempotency(conn, monkeypatch):
    from edu_platform.br45.risk import refresh as refresh_risk

    monkeypatch.setenv("EDU_BR45_AUTH", json.dumps({
        "advisor": {"id": "advisor", "role": "advisor", "courses": ["c"]},
        "other": {"id": "other", "role": "advisor", "courses": ["different"]},
    }))
    settings.cache_clear()
    try:
        source(conn, 1)
        load(conn, "enrollments", {
            "id": "enrolled", "student_id": "s0", "course_id": "c", "status": "active",
            "enrolled_at": (T - timedelta(days=35)).isoformat(),
        })
        state(conn, "evaluation_clock", T.isoformat())
        persist(conn, risk())
        alert_id = conn.execute("SELECT id FROM analytics.dropout_alerts").fetchone()["id"]
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[database] = lambda: conn
        headers = {"Authorization": "Bearer advisor"}
        outside = {"Authorization": "Bearer other"}
        policy_path = "/api/advisor/courses/c/policy"
        note_path = f"/api/advisor/alerts/{alert_id}/notes"
        with TestClient(app) as client:
            assert client.get(policy_path, headers=outside).status_code == 403
            default = client.get(policy_path, headers=headers).json()
            assert default["version"] == 1
            update = {"expected_version": 1, "parameters": {
                **default["parameters"], "alert_threshold": 80,
            }}
            assert client.put(policy_path, headers=headers, json=update).json()["version"] == 2
            assert client.put(policy_path, headers=headers, json=update).status_code == 409
            assert client.get(note_path, headers=outside).status_code == 403
            body = {"idempotency_key": "one", "note": "Called to discuss the assignment"}
            first = client.post(note_path, headers=headers, json=body)
            second = client.post(note_path, headers=headers, json=body)
            assert first.status_code == second.status_code == 201
            assert first.json() == second.json()
            assert first.json()["actor"] == "advisor"
            assert client.post(
                note_path, headers=headers, json=body | {"note": "Different note"}
            ).status_code == 409
            assert len(client.get(note_path, headers=headers).json()) == 1

        for boundary, version in ((T, 1), (T + timedelta(hours=1), 2)):
            refresh_risk(conn, boundary)
            row = conn.execute(
                "SELECT data FROM analytics.risk_state WHERE student_id='s0'"
            ).fetchone()
            assert row["data"]["policy_version"] == version
    finally:
        settings.cache_clear()


def test_risk_history_outbox_distinguishes_equal_score_observations(conn):
    result = risk()
    corrected = {
        **result,
        "reasons": [{**result["reasons"][0], "reason": "Corrected contributing activity"}],
    }
    for observation in (result, corrected, corrected):
        persist(conn, observation)
    rows = list(conn.execute(
        "SELECT event_id,payload FROM analytics.domain_outbox WHERE topic='risk.learner_score.v1'"
    ))
    assert len(rows) == 2
    assert rows[0]["event_id"] != rows[1]["event_id"]
    assert rows[0]["payload"]["score"] == rows[1]["payload"]["score"]


def test_risk_refresh_waits_for_matching_committed_sink(conn, monkeypatch):
    from edu_platform.br45 import streaming

    calls = []
    monkeypatch.setattr(streaming, "refresh", lambda *args, **kwargs: calls.append(args))
    cfg = AnalyticsSettings(checkpoint="/test/checkpoint")
    progress = {"batchId": 3, "sources": [{"endOffset": {cfg.activity_topic: {"0": 8}}}]}
    state(conn, "published_offsets", {"0": 8})
    state(conn, "evaluation_clock", T.isoformat())
    state(conn, "stream", {"checkpoint": cfg.checkpoint, "batch_id": 2})
    streaming.score_committed_batch(conn, progress, cfg)
    assert not calls
    state(conn, "stream", {"checkpoint": cfg.checkpoint, "batch_id": 3})
    streaming.score_committed_batch(conn, {"sources": [{"endOffset": None}]}, cfg)
    assert not calls
    streaming.score_committed_batch(conn, progress, cfg)
    assert len(calls) == 1

    offsets = {cfg.activity_topic: {"0": 8}}
    idle = {
        "batchId": 4, "numInputRows": 0,
        "sources": [{"startOffset": offsets, "endOffset": offsets}],
    }
    streaming.score_committed_batch(conn, idle, cfg)
    assert len(calls) == 2
    state(conn, "published_offsets", {"0": 9})
    streaming.score_committed_batch(conn, idle, cfg)
    assert len(calls) == 2


def test_failed_generation_leaves_the_last_assessment_publication(conn):
    from edu_platform.br45 import jobs

    source(conn)
    before, _ = results(conn)
    start = T - timedelta(days=30)
    cfg = AnalyticsSettings(assessment_engine="postgres")
    job = jobs.request(conn, "c", start, T, cfg)
    claimed = jobs.pending(conn, "postgres")
    assert claimed and claimed["id"] == job["id"]
    with pytest.raises(RuntimeError, match="lease was lost"), conn.transaction():
        conn.execute("DELETE FROM analytics.mart_question_pass_statistics WHERE course_id='c'")
        jobs.complete(
            conn, claimed | {"lease_generation": claimed["lease_generation"] - 1},
            "stale", "stale-publication",
        )
    jobs.fail(conn, claimed, RuntimeError("injected publication failure"))
    after = conn.execute(
        "SELECT data FROM analytics.mart_question_pass_statistics WHERE course_id='c'"
    ).fetchone()
    assert after["data"] == before[0]
    status = conn.execute("SELECT status FROM analytics.assessment_jobs").fetchone()["status"]
    assert status == "FAILED"


def test_retention_dry_run_blocks_while_job_or_outbox_pending(conn):
    from edu_platform.br45 import jobs
    from edu_platform.br45.retention import activity_deliveries

    cfg = AnalyticsSettings()
    published = {"0": 8}
    state(conn, "published_offsets", published)
    state(conn, "feature_freshness", {"caught_up": True, "published_offsets": published})
    state(conn, "stream_watermark", T.isoformat())
    conn.execute(
        "INSERT INTO analytics.outbox(event_id,payload,published_at) "
        "VALUES ('old',jsonb_build_object('event_time',%s::text),now()-interval '90 days')",
        (T.isoformat(),),
    )
    preview = activity_deliveries(conn, cfg, 60)
    assert preview["status"] == "PREVIEW" and preview["eligible"] == 1
    assert conn.execute("SELECT count(*) n FROM analytics.outbox").fetchone()["n"] == 1
    job = jobs.request(conn, "c", T - timedelta(days=30), T)
    assert activity_deliveries(conn, cfg, 60, apply=True)["status"] == "BLOCKED"
    conn.execute(
        "UPDATE analytics.assessment_jobs SET status='SUCCEEDED' WHERE id=%s", (job["id"],)
    )
    conn.execute("INSERT INTO analytics.outbox(event_id,payload) VALUES ('pending','{}')")
    blocked = activity_deliveries(conn, cfg, 60, apply=True)
    assert blocked["status"] == "BLOCKED" and blocked["pending"]["pending"]
    assert conn.execute("SELECT count(*) n FROM analytics.outbox").fetchone()["n"] == 2


def test_postgres_worker_publishes_after_its_previous_lease_expires(conn, monkeypatch):
    from contextlib import nullcontext

    from edu_platform.br45 import jobs

    source(conn)
    cfg = AnalyticsSettings(assessment_engine="postgres")
    job = jobs.request(conn, "c", T - timedelta(days=30), T, cfg)
    abandoned = jobs.pending(conn, "postgres")
    assert abandoned and abandoned["id"] == job["id"]
    conn.execute(
        "UPDATE analytics.assessment_jobs SET started_at=now()-interval '31 minutes' WHERE id=%s",
        (job["id"],),
    )
    monkeypatch.setattr(jobs, "connect", lambda: nullcontext(conn))
    jobs.process_postgres(cfg)
    final = conn.execute("SELECT * FROM analytics.assessment_jobs").fetchone()
    assert final["status"] == "SUCCEEDED"
    assert final["published_engine"] == "postgres"
    assert final["published_revision"] == job["requested_revision"]
    assert final["lease_generation"] > abandoned["lease_generation"]
    assert final["source_delta_version"] is None
    metric = conn.execute("SELECT data FROM analytics.mart_question_pass_statistics").fetchone()
    assert metric["data"]["passed_evaluations"] == 2

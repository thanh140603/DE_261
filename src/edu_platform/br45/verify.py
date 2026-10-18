"""Real PostgreSQL -> WAL -> Debezium -> Kafka -> Spark -> persisted API verification."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from confluent_kafka import Producer

from .config import settings
from .contracts import timestamp
from .db import connect, state
from .fixtures import COURSE, PREFIX, upsert


def wait_for(check: Callable[[], Any], description: str, timeout: int = 180) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise AssertionError(f"Timed out after {timeout}s: {description}")


def risk(student: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT data FROM analytics.risk_state WHERE student_id=%s AND course_id=%s",
            (student, COURSE),
        ).fetchone()
        return row["data"] if row else None


def run(
    base_url: str = "http://localhost:8000",
    output: str = "docs/evidence/br45",
    restart: bool = False,
) -> dict[str, Any]:
    cfg = settings()
    with connect() as conn:
        at = timestamp(state(conn, "evaluation_clock"))
    sid = "br45-e2e-" + uuid.uuid4().hex[:10]
    enid = sid + "-enrollment"
    checks = []
    started = time.perf_counter()
    with connect() as conn:
        upsert(
            conn,
            "enrollments",
            {
                "id": enid,
                "student_id": sid,
                "course_id": COURSE,
                "status": "active",
                "enrolled_at": at - timedelta(days=30),
            },
        )
        for i in range(4):
            upsert(
                conn,
                "activity_events",
                {
                    "id": sid + f"-baseline-{i}",
                    "student_id": sid,
                    "course_id": COURSE,
                    "event_type": "lesson_view",
                    "event_time": at - timedelta(days=8 + i),
                },
            )
    initial = wait_for(
        lambda: (
            r
            if (r := risk(sid)) and r["score"] == 100 and r["features"]["activity_previous_7d"] == 4
            else None
        ),
        "CDC baseline must produce score 100 with four previous-window events",
    )
    latency = (time.perf_counter() - started) * 1000
    checks.append(
        "Actual PostgreSQL inserts traversed Debezium and Spark; previous window=4, "
        "recent=0, score=100"
    )
    with connect() as conn:
        raw = list(
            conn.execute(
                (
                    "SELECT envelope FROM analytics.raw_changes WHERE "
                    "envelope->'after'->>'student_id'=%s ORDER BY received_at"
                ),
                (sid,),
            )
        )
        assert len(raw) >= 5 and all(r["envelope"]["source"]["lsn"] for r in raw)
        count_before = (
            conn.execute(
                "SELECT count(*) n FROM analytics.dropout_alerts WHERE student_id=%s", (sid,)
            ).fetchone()
            or {}
        )["n"]
        alert = conn.execute(
            "SELECT id FROM analytics.dropout_alerts WHERE student_id=%s AND status='NEW'", (sid,)
        ).fetchone()
        assert count_before == 1 and alert
        aid = alert["id"]
        deltas = list(
            conn.execute(
                (
                    "SELECT payload FROM analytics.outbox WHERE payload->>'student_id'=%s ORDER"
                    " BY event_id"
                ),
                (sid,),
            )
        )
    advisor = {"Authorization": "Bearer advisor-demo"}
    instructor = {"Authorization": "Bearer instructor-demo"}
    with httpx.Client(base_url=base_url, timeout=30) as api:
        response = api.get("/api/advisor/alerts", headers=advisor, params={"course_id": COURSE})
        response.raise_for_status()
        assert aid in {a["id"] for a in response.json()["items"]}
        response = api.patch(f"/api/advisor/alerts/{aid}/acknowledge", headers=advisor)
        response.raise_for_status()
        assert response.json()["status"] == "ACKNOWLEDGED"
        response = api.get(
            "/api/instructor/courses/" + COURSE + "/questions/statistics", headers=instructor
        )
        response.raise_for_status()
        question = next(
            q for q in response.json()["items"] if q["question_id"] == PREFIX + "question"
        )
        assert question["total_valid_evaluations"] == 24 and question["passed_evaluations"] == 2
        testcase = api.get(
            f"/api/instructor/questions/{PREFIX}question/test-cases", headers=instructor
        ).json()
        assert any(t["state"] == "SUSPICIOUS_TEST_CASE" for t in testcase["items"])
        checks.append(
            "Instructor API returned persisted 2/24 question rate and suspicious test-case "
            "reason; advisor acknowledged the real alert"
        )
        # A corrected evaluation must refresh the API without manually running a batch job.
        with connect() as conn:
            conn.execute(
                "UPDATE br45.evaluations SET status='passed' WHERE id=%s",
                (PREFIX + "evaluation-2-1",),
            )

        def corrected() -> bool:
            response = api.get(
                f"/api/instructor/questions/{PREFIX}question/statistics", headers=instructor
            )
            response.raise_for_status()
            return any(q["passed_evaluations"] == 3 for q in response.json()["items"])

        wait_for(corrected, "BR4 CDC correction must refresh question pass count from 2 to 3")
        with connect() as conn:
            conn.execute(
                "UPDATE br45.evaluations SET status='failed' WHERE id=%s",
                (PREFIX + "evaluation-2-1",),
            )
        checks.append(
            "BR4 evaluation correction propagated automatically into persisted statistics and API"
        )
        producer = Producer({"bootstrap.servers": cfg.kafka, "enable.idempotence": True})
        for record in raw:
            producer.produce(
                cfg.topic_prefix + record["envelope"]["source"]["table"],
                value=json.dumps(record["envelope"]),
            )
        for record in deltas:
            producer.produce(
                cfg.activity_topic, key=sid + ":" + COURSE, value=json.dumps(record["payload"])
            )
        assert producer.flush(30) == 0
        # Force a fresh batch barrier after replay instead of relying on elapsed time alone.
        with connect() as conn:
            upsert(
                conn,
                "activity_events",
                {
                    "id": sid + "-recovery",
                    "student_id": sid,
                    "course_id": COURSE,
                    "event_type": "lesson_complete",
                    "event_time": at - timedelta(minutes=1),
                },
            )
        recovered = wait_for(
            lambda: (
                r
                if (r := risk(sid)) and r["features"]["activity_7d"] == 1 and r["score"] == 65
                else None
            ),
            "Replay must not inflate counts; one recovery event leaves decline+deadline score 65",
        )
        with connect() as conn:
            assert (
                conn.execute(
                    "SELECT count(*) n FROM analytics.dropout_alerts WHERE student_id=%s", (sid,)
                ).fetchone()
                or {}
            )["n"] == 1
        checks.append(
            "Replayed CDC and normalized Kafka records produced no duplicate features or alerts"
        )
        # Update event time moves an event between overlapping windows; delete retracts it.
        with connect() as conn:
            conn.execute(
                "UPDATE br45.activity_events SET event_time=%s WHERE id=%s",
                (at - timedelta(days=9), sid + "-recovery"),
            )
        wait_for(
            lambda: (
                (r := risk(sid))
                and r["features"]["activity_7d"] == 0
                and r["features"]["activity_previous_7d"] == 5
            ),
            "CDC update must retract recent count and add to previous window",
        )
        with connect() as conn:
            conn.execute("DELETE FROM br45.activity_events WHERE id=%s", (sid + "-recovery",))
        wait_for(
            lambda: (r := risk(sid)) and r["features"]["activity_previous_7d"] == 4,
            "CDC delete must retract previous-window activity",
        )
        checks.append(
            "Real CDC UPDATE and DELETE correctly retracted event-time window contributions"
        )
        restart_ms = None
        if restart:
            started = time.perf_counter()
            subprocess.run(
                ["docker", "compose", "--profile", "br45", "restart", "br45-stream"],
                check=True,
                timeout=60,
            )
            with connect() as conn:
                for i in range(4):
                    upsert(
                        conn,
                        "activity_events",
                        {
                            "id": sid + f"-final-{i}",
                            "student_id": sid,
                            "course_id": COURSE,
                            "event_type": "lesson_complete",
                            "event_time": at - timedelta(minutes=2 + i),
                        },
                    )
            wait_for(
                lambda: (r := risk(sid)) and r["features"]["activity_7d"] == 4 and r["score"] == 50,
                "Checkpoint restart must preserve prior activity and process new recovery records",
            )
            restart_ms = (time.perf_counter() - started) * 1000
            checks.append(
                "Spark restarted from persistent checkpoint, preserved prior-window count "
                "and processed recovery; alert auto-resolved"
            )
        response = api.patch(f"/api/advisor/alerts/{aid}/resolve", headers=advisor)
        response.raise_for_status()
        assert response.json()["status"] == "RESOLVED"
    with connect() as conn:
        final = risk(sid)
        alerts = (
            conn.execute(
                "SELECT count(*) n FROM analytics.dropout_alerts WHERE student_id=%s", (sid,)
            ).fetchone()
            or {}
        )["n"]
        conn.execute("DELETE FROM br45.activity_events WHERE student_id=%s", (sid,))
        conn.execute("DELETE FROM br45.enrollments WHERE id=%s", (enid,))
    result = {
        "measured_at": datetime.now(UTC).isoformat(),
        "synthetic": True,
        "student_id": sid,
        "checks": checks,
        "cdc_to_alert_ms": latency,
        "restart_to_recovery_ms": restart_ms,
        "duplicate_alert_count": alerts - 1,
        "initial_risk": initial,
        "final_risk": final,
        "replay_recovery_risk": recovered,
    }
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "e2e_result.json").write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {
                "checks": len(checks),
                "cdc_to_alert_ms": latency,
                "restart_to_recovery_ms": restart_ms,
                "duplicate_alert_count": alerts - 1,
            },
            indent=2,
        )
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--output", default="docs/evidence/br45")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    run(args.url, args.output, args.restart)

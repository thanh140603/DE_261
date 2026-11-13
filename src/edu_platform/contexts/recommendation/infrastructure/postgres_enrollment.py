"""PostgreSQL enrollment adapter (BR2/BR1 shared write path).

The LMS Postgres is the system of record for enrolment. The demo keeps an
in-process mirror for the recommender; when the API runs in ``service`` mode it
must write this table too, otherwise the notification service's audience query
never sees a learner who enrolled through the UI.
"""

from __future__ import annotations

from typing import Any


class PostgresEnrollmentRepository:
    def __init__(self, postgres_dsn: str) -> None:
        self._dsn = postgres_dsn

    def enroll(self, learner_id: str, course_id: str, organisation_id: str | None) -> None:
        import psycopg

        enrollment_id = f"e-{learner_id}-{course_id}"
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                INSERT INTO enrollments
                    (enrollment_id, learner_id, course_id, organisation_id, status)
                VALUES (%s, %s, %s, %s, 'active')
                ON CONFLICT (enrollment_id) DO UPDATE
                    SET status = 'active', updated_at = now()
                """,
                (enrollment_id, learner_id, course_id, organisation_id),
            )

    def complete(self, learner_id: str, course_id: str) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                "UPDATE enrollments SET status = 'completed', updated_at = now() "
                "WHERE learner_id = %s AND course_id = %s",
                (learner_id, course_id),
            )

    def list_course_ids(self, learner_id: str) -> list[str]:
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            rows: Any = conn.execute(
                "SELECT course_id FROM enrollments "
                "WHERE learner_id = %s AND status IN ('active', 'completed') "
                "ORDER BY enrolled_at",
                (learner_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

"""PostgreSQL store for BR3-owned grading history.

Redis is the hot store (7-day TTL) and Kafka is the transport. The durable
submission/grade rows live in the ``grading`` schema, owned by this context; the
optional grading projector copies them to the LMS ``public`` schema for
CDC/lakehouse consumers. Every write is an idempotent UPSERT keyed by
``submission_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from edu_platform.contexts.grading.domain.model import Submission


class PostgresGradingStore:
    def __init__(self, postgres_dsn: str) -> None:
        self._dsn = postgres_dsn

    def record_queued(self, submission: Submission) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                INSERT INTO grading.submissions
                    (submission_id, learner_id, assignment_id, attempt_number,
                     language, code_ref, status, submitted_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (submission_id) DO UPDATE
                    SET status = EXCLUDED.status, updated_at = now()
                """,
                (
                    submission.id,
                    submission.learner_id,
                    submission.assignment_id,
                    submission.attempt_number,
                    submission.language.value,
                    submission.code_ref,
                    submission.status.value,
                    submission.submitted_at,
                ),
            )

    def record_graded(self, submission: Submission) -> None:
        import psycopg

        if submission.result is None:
            return
        pass_rate = submission.result.pass_rate
        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                INSERT INTO grading.submissions
                    (submission_id, learner_id, assignment_id, attempt_number,
                     language, code_ref, status, submitted_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (submission_id) DO UPDATE
                    SET status = EXCLUDED.status, updated_at = now()
                """,
                (
                    submission.id,
                    submission.learner_id,
                    submission.assignment_id,
                    submission.attempt_number,
                    submission.language.value,
                    submission.code_ref,
                    submission.status.value,
                    submission.submitted_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO grading.grades (submission_id, score, pass_rate, graded_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (submission_id) DO UPDATE
                    SET score = EXCLUDED.score,
                        pass_rate = EXCLUDED.pass_rate,
                        graded_at = EXCLUDED.graded_at
                """,
                (
                    submission.id,
                    round(pass_rate * 100, 2),
                    round(pass_rate, 4),
                    datetime.now(tz=UTC),
                ),
            )

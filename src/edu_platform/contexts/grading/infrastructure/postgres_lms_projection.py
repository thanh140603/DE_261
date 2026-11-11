"""Projector read model: BR3 grading events -> the LMS public tables (BR3 projector).

This is the only component that writes the LMS ``public.submissions``/``grades``
from BR3 after Phase 5. It is deliberately separate from the grading service and
is opt-in (compose profile ``br13-project``): by default the LMS schema is left
untouched, so BR4/BR6 data stays on its existing baseline.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class PostgresLmsGradingProjection:
    def __init__(self, postgres_dsn: str) -> None:
        self._dsn = postgres_dsn

    def record_queued(self, payload: dict[str, Any]) -> None:
        import psycopg

        with psycopg.connect(self._dsn) as conn:
            conn.execute(
                """
                INSERT INTO public.submissions
                    (submission_id, learner_id, assignment_id, attempt_number,
                     language, code_ref, status, submitted_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'queued', %s, now())
                ON CONFLICT (submission_id) DO UPDATE
                    SET status = CASE
                            WHEN submissions.status = 'graded' THEN 'graded'
                            ELSE EXCLUDED.status
                        END,
                        updated_at = now()
                """,
                (
                    payload["submission_id"],
                    payload["learner_id"],
                    payload["assignment_id"],
                    payload.get("attempt_number", 1),
                    payload["language"],
                    payload["code_ref"],
                    payload["submitted_at"],
                ),
            )

    def record_graded(self, payload: dict[str, Any]) -> None:
        import psycopg

        pass_rate = float(payload["pass_rate"])
        snapshot = ("language", "code_ref", "attempt_number", "submitted_at")
        with psycopg.connect(self._dsn) as conn:
            if all(key in payload for key in snapshot):
                conn.execute(
                    """
                    INSERT INTO public.submissions
                        (submission_id, learner_id, assignment_id, attempt_number,
                         language, code_ref, status, submitted_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'graded', %s, now())
                    ON CONFLICT (submission_id) DO UPDATE
                        SET status = 'graded', updated_at = now()
                    """,
                    (
                        payload["aggregate_id"],
                        payload["learner_id"],
                        payload["assignment_id"],
                        payload["attempt_number"],
                        payload["language"],
                        payload["code_ref"],
                        payload["submitted_at"],
                    ),
                )
            else:
                # Backward compatibility with events produced before the snapshot
                # fields were added: only update an existing queued row.
                cursor = conn.execute(
                    "UPDATE public.submissions SET status = 'graded', updated_at = now() "
                    "WHERE submission_id = %s",
                    (payload["aggregate_id"],),
                )
                if cursor.rowcount == 0:
                    raise ValueError("graded event lacks snapshot and no public submission exists")
            conn.execute(
                """
                INSERT INTO public.grades (submission_id, score, pass_rate, graded_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (submission_id) DO UPDATE
                    SET score = EXCLUDED.score,
                        pass_rate = EXCLUDED.pass_rate,
                        graded_at = EXCLUDED.graded_at
                """,
                (
                    payload["aggregate_id"],
                    round(pass_rate * 100, 2),
                    round(pass_rate, 4),
                    datetime.now(tz=UTC),
                ),
            )

"""Server-side study routines driven by a durable logical classroom clock."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import psycopg

from edu_platform.demo import seed
from edu_platform.demo.simulator import Simulator
from edu_platform.platform.logging import get_logger

from .classroom import CLOCK_ID, StudyError, lesson_activity, submit
from .contracts import timestamp
from .db import connect, state

log = get_logger(__name__)
FIZZBUZZ = """def fizzbuzz(n):
    return [
        "FizzBuzz" if i % 15 == 0 else "Fizz" if i % 3 == 0 else "Buzz" if i % 5 == 0 else str(i)
        for i in range(1, n + 1)
    ]
"""
SQL_JOINS = """SELECT s.name, COUNT(*) AS courses
FROM students s JOIN enrollments e ON e.student_id = s.id
GROUP BY s.id, s.name HAVING COUNT(*) >= 2 ORDER BY s.name;
"""


def study(sim: Simulator, step: int) -> None:
    request = f"bot-{step}"
    kind = "lesson_view" if step % 2 == 0 else "lesson_complete"
    lesson = seed.course("c-py-201").lessons[(step // 2) % 3].id
    lesson_activity("l-004", lesson, kind, request)
    if step % 6 == 2:
        lesson_activity("l-006", "l-sql-2", "lesson_view", request)
    elif step % 6 == 3:
        lesson_activity("l-006", "l-sql-2", "lesson_complete", request)
        submit(sim, "l-006", "a-sql-joins", SQL_JOINS, request)
    if step % 4 == 0:
        lesson_activity("l-007", "l-py-1", "lesson_view", request)
    elif step % 4 == 1:
        submit(sim, "l-007", "a-py-fizz", "def fizzbuzz(n):\n    return []\n", request)
    elif step % 4 == 2:
        lesson_activity("l-007", "l-py-1", "lesson_complete", request)
    else:
        submit(sim, "l-007", "a-py-fizz", FIZZBUZZ, request)


def cycle(sim: Simulator) -> None:
    with connect() as conn:
        # A failed cycle keeps its step number. Previously committed actions are idempotent.
        row = conn.execute("SELECT next_step FROM classroom.run FOR UPDATE").fetchone()
        clock = conn.execute(
            "SELECT evaluated_at FROM br45.clocks WHERE id=%s", (CLOCK_ID,)
        ).fetchone()
        refresh = state(conn, "risk_refresh")
        if not row or not clock or not refresh:
            return
        at = clock["evaluated_at"]
        if timestamp(refresh["evaluated_at"]) != at:
            return
        study(sim, row["next_step"])
        conn.execute(
            "UPDATE br45.clocks SET evaluated_at=%s WHERE id=%s",
            (at + timedelta(hours=1), CLOCK_ID),
        )
        conn.execute("UPDATE classroom.run SET next_step=next_step+1")


async def run(sim: Simulator) -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(cycle, sim)
        except (psycopg.Error, StudyError):
            log.exception("Classroom study cycle failed and will retry")

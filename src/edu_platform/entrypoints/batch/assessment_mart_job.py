"""Executable BR4 SQL mart refresh over CDC-cleaned PostgreSQL facts (ADR 0009)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import typer

from edu_platform.br45.assessment import refresh
from edu_platform.br45.db import connect


def main(run_date: str = typer.Option(..., help="Partition to process, YYYY-MM-DD")) -> None:
    try:
        day = date.fromisoformat(run_date)
    except ValueError as exc:
        raise typer.BadParameter("Use YYYY-MM-DD for --run-date") from exc
    end = datetime.combine(day + timedelta(days=1), time.min, UTC)
    with connect() as conn:
        questions, cases = refresh(conn, end - timedelta(days=30), end)
    typer.echo(f"Persisted {len(questions)} question and {len(cases)} test-case statistics")


if __name__ == "__main__":
    typer.run(main)

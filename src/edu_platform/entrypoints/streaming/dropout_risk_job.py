"""Executable BR5 Spark Structured Streaming job (ADR 0009).

Run with the br45-stream Compose service. CDC ingestion runs separately in
edu_platform.br45.cdc, preserving transactional raw/clean/outbox state.
"""

from __future__ import annotations


def main() -> None:
    from edu_platform.br45.streaming import run

    run()


if __name__ == "__main__":
    main()

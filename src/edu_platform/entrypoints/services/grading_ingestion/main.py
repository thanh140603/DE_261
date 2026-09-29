"""Grading Ingestion Service (BR3) - decouples LMS submissions from sandbox workers.

Content (TODO):
- HTTP (FastAPI) POST /submissions -> EnqueueSubmission (202 Accepted immediately).
- Kafka consumer on grading.sandbox_result.raw.v1 -> NormalizeExecutionLog.
- Back-pressure: bounded in-flight per worker; sandbox worker autoscaling is driven by
  consumer lag on grading.submission_received.v1.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

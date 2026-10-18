"""Flink job: dropout_risk_job (BR5).

Content (TODO):
- Sources: cdc.lms.public.{lesson_progress,submissions,grades,enrollments} (Debezium
  envelope, ordered by LSN) + login/attempt telemetry.
- SignalExtractor per source -> RiskSignal; key by (learner, course).
- Sliding window (SlidingWindowPolicy: 14 d size / 1 d slide) -> RiskScoringPolicy.
- ScoreLearnerRisk emits DropoutRiskDetected -> risk.dropout_alert.v1 and Redis score.
- Every rescore is also published to risk.learner_score.v1
  (schemas/risk/v1/learner_score.schema.json) -> gold.fct_risk_score_daily (advisor trend).
Wiring: platform.streaming.flink_env.build_stream_env -> kafka_source(s) with event-time
watermarks -> keyed process function calling the context use case -> kafka/redis/delta sinks.
Checkpointing exactly-once; state TTL aligned with the domain window policy.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

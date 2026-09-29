"""Notification Service (BR1) - long-running Kafka consumer + tiny HTTP admin API.

Content (TODO):
- Consume lms.assignment_created.v1, lms.deadline_approaching.v1, lms.course_updated.v1,
  grading.submission_graded.v1, risk.dropout_alert.v1 (consumer group edu-notification).
- Wire: YamlRuleRepository -> RuleEngine; RedisNotificationState; CdcAudienceResolver;
  senders {push, in_app, email}; RouteEvent -> DispatchNotification.
- FastAPI: /healthz, /readyz, POST /rules/reload, GET /metrics (Prometheus).
- Graceful shutdown; DLQ on repeated handler failure (platform.messaging.kafka_consumer).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError  # TODO


if __name__ == "__main__":
    main()

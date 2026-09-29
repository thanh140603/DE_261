"""Single source of truth for Kafka topic names.

Naming: ``<context>.<entity-or-event>.<version>``. The same list drives
``infra/kafka/topics.yaml`` (partitions / retention) - keep them in sync.
"""

from __future__ import annotations

from enum import StrEnum


class Topic(StrEnum):
    # Raw ingestion
    TELEMETRY_RAW = "telemetry.events.raw.v1"
    TELEMETRY_DLQ = "telemetry.events.dlq.v1"
    # Debezium CDC (prefix configured in infra/debezium/postgres-connector.json)
    CDC_ENROLLMENTS = "cdc.lms.public.enrollments"
    CDC_PROGRESS = "cdc.lms.public.lesson_progress"
    CDC_SUBMISSIONS = "cdc.lms.public.submissions"
    CDC_GRADES = "cdc.lms.public.grades"
    CDC_COURSE_CONTENT = "cdc.lms.public.course_content"
    # Grading (BR3)
    SUBMISSION_RECEIVED = "grading.submission_received.v1"
    SANDBOX_RESULT_RAW = "grading.sandbox_result.raw.v1"
    SUBMISSION_GRADED = "grading.submission_graded.v1"
    # Risk (BR5)
    DROPOUT_RISK_ALERT = "risk.dropout_alert.v1"
    # LMS business events (BR1)
    ASSIGNMENT_CREATED = "lms.assignment_created.v1"
    DEADLINE_APPROACHING = "lms.deadline_approaching.v1"
    COURSE_UPDATED = "lms.course_updated.v1"
    NOTIFICATION_DISPATCHED = "notification.dispatched.v1"
    # Content (BR8)
    CONTENT_UPDATED = "content.updated.v1"
    CONTENT_INDEXED = "content.indexed.v1"
    # Features (BR2)
    SESSION_FEATURES = "features.session.v1"

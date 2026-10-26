"""Domain objects -> JSON-ready dicts for the API and SSE (shapes: docs/api.md)."""

from __future__ import annotations

from typing import Any

from edu_platform.contexts.grading.domain.model import Submission, TestCaseResult
from edu_platform.contexts.notification.domain.model import Notification
from edu_platform.contexts.recommendation.domain.model import LongTermFeatures
from edu_platform.contexts.telemetry.domain.events import LearningEvent


def learning_event_dict(e: LearningEvent) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "learner_pseudonym": e.learner_pseudonym,
        "course_id": e.course_id,
        "content_id": e.content_id,
        "session_id": e.session_id,
        "verb": e.verb.value,
        "platform": e.platform.value,
        "occurred_at": e.occurred_at.isoformat(),
        "received_at": e.received_at.isoformat(),
        "lateness_seconds": round(e.lateness_seconds, 1),
        "video_position_sec": e.video_position.second if e.video_position else None,
        "schema_version": str(e.schema_version),
        "late": e.is_late,
    }


def test_dict(t: TestCaseResult) -> dict[str, Any]:
    return {
        "test_case_id": t.test_case_id,
        "status": t.status.value,
        "expected": t.expected,
        "actual": t.actual,
        "diff": t.diff,
        "duration_ms": t.duration_ms,
    }


def submission_dict(s: Submission, *, include_stdout: bool = True) -> dict[str, Any]:
    result = None
    if s.result is not None:
        result = {
            "stderr": s.result.stderr,
            "runtime_ms": s.result.runtime_ms,
            "memory_kb": s.result.memory_kb,
            "exit_code": s.result.exit_code,
            "pass_rate": round(s.result.pass_rate, 3),
            "tests": [test_dict(t) for t in s.result.tests],
        }
        if include_stdout:
            result["stdout"] = s.result.stdout
    feedback = None
    if s.feedback is not None:
        feedback = {
            "summary": s.feedback.summary,
            "failed_tests": [test_dict(t) for t in s.feedback.failed_tests],
            "stderr_excerpt": s.feedback.stderr_excerpt,
            "hints": list(s.feedback.hints),
        }
    return {
        "id": s.id,
        "learner_id": s.learner_id,
        "assignment_id": s.assignment_id,
        "language": s.language.value,
        "status": s.status.value,
        "attempt_number": s.attempt_number,
        "submitted_at": s.submitted_at.isoformat(),
        "result": result,
        "feedback": feedback,
    }


def notification_dict(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "title": n.content.title,
        "body": n.content.body,
        "channels": [c.value for c in n.channels],
        "priority": n.priority.value,
        "created_at": n.created_at.isoformat(),
        "source_event_type": n.source_event_type,
        "deep_link": n.content.deep_link,
    }


def longterm_dict(f: LongTermFeatures | None) -> dict[str, Any] | None:
    if f is None:
        return None
    return {
        "completion_rate_30d": f.completion_rate_30d,
        "avg_pass_rate_30d": f.avg_pass_rate_30d,
        "active_days_30d": f.active_days_30d,
        "preferred_platform": f.preferred_platform,
        "skill_mastery": f.skill_mastery,
        "computed_at": f.computed_at.isoformat(),
    }

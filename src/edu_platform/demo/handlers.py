"""Event consumers of the demo (the "consumer groups").

Each function is what one production service / Flink operator does; here they
are subscribed to the in-process bus. Wiring is explicit so the data flow can
be read top to bottom:

    telemetry.events.raw.v1     -> normalise -> silver | dlq -> session features
    cdc.lms.*                   -> risk signals -> sliding-window score -> alert
    grading.submission_graded   -> learner feedback notification, risk signal
    risk.dropout_alert.v1       -> advisor notification
    lms.*                       -> learner notifications (rules)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.notification.application.route_event import RouteEventCommand
from edu_platform.contexts.risk.application.score_learner_risk import ScoreLearnerRiskCommand
from edu_platform.contexts.telemetry.domain.events import RawEvent, SchemaVersion
from edu_platform.demo import seed
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.event_bus import Message
from edu_platform.demo.serializers import learning_event_dict
from edu_platform.platform.messaging.topics import Topic
from edu_platform.shared_kernel.domain import DomainError
from edu_platform.shared_kernel.domain.ids import LearnerId

CDC_TOPICS = {
    "lesson_progress": Topic.CDC_PROGRESS,
    "submissions": Topic.CDC_SUBMISSIONS,
    "grades": Topic.CDC_GRADES,
    "enrollments": Topic.CDC_ENROLLMENTS,
}


def register(p: DemoPlatform) -> None:
    p.bus.subscribe(Topic.TELEMETRY_RAW, lambda m: on_raw_telemetry(p, m))
    for topic in CDC_TOPICS.values():
        p.bus.subscribe(topic, lambda m: on_cdc_change(p, m))
    p.bus.subscribe("grading.submission_graded.v1", lambda m: on_submission_graded(p, m))
    p.bus.subscribe("risk.dropout_risk_detected.v1", lambda m: on_dropout_alert(p, m))
    for topic in (Topic.ASSIGNMENT_CREATED, Topic.DEADLINE_APPROACHING, Topic.COURSE_UPDATED):
        p.bus.subscribe(topic, lambda m: on_lms_event(p, m))
    p.bus.subscribe("notification.suppressed.v1", lambda m: _count_suppressed(p))


# --- telemetry ---------------------------------------------------------------
def on_raw_telemetry(p: DemoPlatform, msg: Message) -> None:
    payload = msg.payload
    try:
        version = SchemaVersion.parse(str(payload.get("schema_version", "1.1")))
    except DomainError:
        version = SchemaVersion(1, 1)
    raw = RawEvent(
        event_id=str(payload.get("event_id") or msg.key),
        raw_learner_id=LearnerId(str(payload.get("learner_id", ""))),
        schema_version=version,
        payload=payload,
        received_at=msg.at,
        source_topic=msg.topic,
        partition=0,
        offset=p.bus.counts[msg.topic],
    )
    p.bronze.append(raw)
    try:
        event = p.normalize.normalize_one(raw)
    except DomainError as exc:
        p.dlq.reject(raw, str(exc))
        p.broadcaster.publish(
            "telemetry.dlq",
            {"event_id": raw.event_id, "reason": str(exc), "verb": payload.get("verb")},
        )
        return
    if not p.silver.upsert(event):
        p.broadcaster.publish("telemetry.duplicate", {"event_id": event.event_id})
        return
    if event.is_late:
        p.late_events += 1
    p.broadcaster.publish("telemetry.silver", learning_event_dict(event))


# --- CDC -> risk ---------------------------------------------------------------
def on_cdc_change(p: DemoPlatform, msg: Message) -> None:
    row = msg.payload
    table = str(row.get("__table", ""))
    at = _ts(row.get("__ts_ms"), msg.at)
    signals = p.signal_rules.from_row_change(table, row, at)
    learner_id, course_id = str(row.get("learner_id", "")), str(row.get("course_id", ""))
    if not learner_id or not course_id:
        return
    result = p.score_risk.execute(ScoreLearnerRiskCommand(learner_id, course_id, signals, at))
    p.broadcaster.publish(
        "risk.score",
        {"learner_id": learner_id, "course_id": course_id, "score": result.score, "table": table},
    )


def observe_risk_signals(
    p: DemoPlatform, learner_id: str, course_id: str, signals: list[Any], at: datetime
) -> Any:
    return p.score_risk.execute(ScoreLearnerRiskCommand(learner_id, course_id, signals, at))


# --- grading -----------------------------------------------------------------
def on_submission_graded(p: DemoPlatform, msg: Message) -> None:
    submission = p.submissions.get(msg.key)  # type: ignore[arg-type]
    if submission is None or submission.feedback is None:
        return
    assignment = seed.assignment(submission.assignment_id)
    payload = {
        **msg.payload,
        "submission_id": submission.id,
        "assignment_title": assignment.title,
        "course_id": assignment.course_id,
        "summary": submission.feedback.summary,
        "deep_link": f"/learner?submission={submission.id}",
    }
    route_and_dispatch(p, msg.payload["event_id"], msg.event_type, payload)
    p.broadcaster.publish(
        "submission.graded",
        {
            "submission_id": submission.id,
            "learner_id": submission.learner_id,
            "assignment_id": submission.assignment_id,
            "pass_rate": submission.result.pass_rate if submission.result else None,
        },
    )
    # repeated failures feed the risk score (BR5)
    recent = sorted(
        (s for s in p.submissions.for_learner(submission.learner_id) if s.result is not None),
        key=lambda s: s.submitted_at,
    )[-3:]
    low = 0
    for s in reversed(recent):
        if s.result is not None and s.result.pass_rate < 0.5:
            low += 1
        else:
            break
    signals = p.signal_rules.from_grading(low, msg.at)
    if signals:
        observe_risk_signals(p, submission.learner_id, assignment.course_id, signals, msg.at)


# --- risk alert -> advisor -----------------------------------------------------
def on_dropout_alert(p: DemoPlatform, msg: Message) -> None:
    learner = seed.learner(str(msg.payload["learner_id"]))
    course = seed.course(str(msg.payload["course_id"]))
    alert: dict[str, Any] = {
        "learner_id": learner.id,
        "learner_name": learner.name,
        "course_id": course.id,
        "course_title": course.title,
        "score": float(msg.payload["score"]),
        "top_signals": list(msg.payload.get("top_signals", [])),
        "at": msg.at.isoformat(),
    }
    p.risk_alerts.append(alert)
    payload = {
        **msg.payload,
        "learner_name": learner.name,
        "course_title": course.title,
        "signals": ", ".join(str(k) for k in alert["top_signals"]).replace("_", " "),
        "deep_link": f"/advisor?learner={learner.id}",
    }
    route_and_dispatch(p, str(msg.payload["event_id"]), msg.event_type, payload)
    p.broadcaster.publish("risk.alert", alert)


# --- LMS events -> learners ------------------------------------------------------
def on_lms_event(p: DemoPlatform, msg: Message) -> None:
    route_and_dispatch(p, msg.key, msg.event_type, msg.payload)


def route_and_dispatch(
    p: DemoPlatform, event_id: str, event_type: str, payload: dict[str, Any]
) -> dict[str, Any]:
    result = p.route_event.execute(RouteEventCommand(event_id, event_type, payload))
    for notification_id in result.created:
        n = p.dispatch.execute(notification_id)
        p.broadcaster.publish(
            "notification",
            {
                "recipient_id": n.recipient_id,
                "title": n.content.title,
                "channels": [c.value for c in n.channels],
                "source_event_type": event_type,
            },
        )
    summary = {
        "created": len(result.created),
        "suppressed": [{"learner_id": r, "reason": reason} for r, reason in result.suppressed],
    }
    p.last_route_result = summary
    return summary


def _count_suppressed(p: DemoPlatform) -> None:
    p.suppressed_count += 1


def _ts(ms: Any, default: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC) if ms else default
    except (TypeError, ValueError):
        return default

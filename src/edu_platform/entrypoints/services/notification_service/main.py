"""Notification Service (BR1) — long-running Kafka consumer.

Consumes the five notification triggers, routes each through the rule engine,
persists the notification and publishes dispatched/suppressed events.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import Any

from edu_platform.contexts.notification.application.dispatch_notification import (
    DispatchNotification,
)
from edu_platform.contexts.notification.application.ports import NotificationSender
from edu_platform.contexts.notification.application.route_event import (
    RouteEvent,
    RouteEventCommand,
)
from edu_platform.contexts.notification.domain.model import Channel, Notification, RateLimitPolicy
from edu_platform.contexts.notification.domain.rule_engine import RuleEngine
from edu_platform.contexts.notification.infrastructure.in_memory import FormatTemplateRenderer
from edu_platform.contexts.notification.infrastructure.postgres_audience import (
    PostgresAudienceResolver,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_repository import (
    RedisNotificationRepository,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_state import (
    RedisNotificationState,
)
from edu_platform.contexts.notification.infrastructure.yaml_rule_repository import (
    YamlRuleRepository,
)
from edu_platform.demo import seed
from edu_platform.platform.clock import SystemClock
from edu_platform.platform.config import get_settings
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.kafka_consumer import KafkaConsumerLoop, KafkaMessage
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client

log = get_logger(__name__)

_TOPICS = [
    Topic.ASSIGNMENT_CREATED.value,
    Topic.DEADLINE_APPROACHING.value,
    Topic.COURSE_UPDATED.value,
    Topic.SUBMISSION_GRADED.value,
    Topic.DROPOUT_RISK_ALERT.value,
]


class InAppSender:
    """The notification is already persisted by RouteEvent; nothing to send."""

    channel = Channel.IN_APP

    def send(self, notification: Notification) -> None:
        return None


class LogSender:
    def __init__(self, channel: Channel) -> None:
        self.channel = channel

    def send(self, notification: Notification) -> None:
        log.info("notification sent", channel=self.channel.value, notification_id=notification.id)


def _senders() -> dict[Channel, NotificationSender]:
    return {
        Channel.IN_APP: InAppSender(),
        Channel.PUSH: LogSender(Channel.PUSH),
        Channel.EMAIL: LogSender(Channel.EMAIL),
    }


def _enrich(client: Any, payload: dict[str, Any], event_type: str) -> dict[str, Any]:
    """Fill template fields the upstream events do not carry."""
    enriched = dict(payload)
    if event_type == Topic.SUBMISSION_GRADED.value:
        assignment_id = payload.get("assignment_id")
        if assignment_id is not None:
            with contextlib.suppress(StopIteration):
                assignment = seed.assignment(str(assignment_id))
                enriched.setdefault("assignment_title", assignment.title)
                enriched.setdefault("course_id", assignment.course_id)
        enriched.setdefault("summary", "Your submission was graded.")
        enriched.setdefault("deep_link", f"/learner?submission={payload.get('aggregate_id')}")
    elif event_type == "risk.dropout_risk_detected.v1":
        learner_id = payload.get("learner_id")
        course_id = payload.get("course_id")
        if learner_id is not None:
            with contextlib.suppress(StopIteration):
                enriched.setdefault("learner_name", seed.learner(str(learner_id)).name)
        if course_id is not None:
            with contextlib.suppress(StopIteration):
                enriched.setdefault("course_title", seed.course(str(course_id)).title)
        enriched.setdefault("signals", ", ".join(payload.get("top_signals", [])))
    return enriched


def _handler(route: RouteEvent, dispatch: DispatchNotification, client: Any) -> Any:
    def handle(message: KafkaMessage) -> None:
        event_type = str(message.payload.get("event_type") or message.topic)
        payload = _enrich(client, message.payload, event_type)
        result = route.execute(
            RouteEventCommand(
                event_id=str(payload.get("event_id") or message.key or ""),
                event_type=event_type,
                payload=payload,
            )
        )
        for notification_id in result.created:
            dispatch.execute(notification_id)

    return handle


def main() -> None:
    settings = get_settings()
    client = create_redis_client(settings.redis_url)
    publisher = KafkaEventPublisher(settings.kafka.bootstrap_servers, client_id="edu-notification")

    root = Path(__file__).resolve().parents[5]
    rules_path = Path(
        os.getenv("EDU_NOTIFICATION_RULES", str(root / "infra" / "notification" / "rules.yaml"))
    )
    rules = YamlRuleRepository(rules_path).all()
    state = RedisNotificationState(client)
    repo = RedisNotificationRepository(client)
    audience = PostgresAudienceResolver(settings.postgres_dsn.get_secret_value())
    renderer = FormatTemplateRenderer()
    clock = SystemClock()

    route = RouteEvent(
        RuleEngine(rules), audience, state, renderer, repo, RateLimitPolicy(), publisher, clock
    )
    dispatch = DispatchNotification(_senders(), repo, publisher, clock)

    loop = KafkaConsumerLoop(
        settings.kafka.bootstrap_servers,
        group_id="edu-notification",
        topics=_TOPICS,
        dlq_publisher=lambda topic, payload: publisher.publish_raw(
            topic, key=None, payload=payload
        ),
    )
    loop.run(_handler(route, dispatch, client))


if __name__ == "__main__":
    main()

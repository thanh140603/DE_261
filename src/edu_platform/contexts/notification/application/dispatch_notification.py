"""Use case: deliver a Notification over each selected channel (BR1)."""

from __future__ import annotations

from edu_platform.contexts.notification.application.ports import (
    NotificationRepository,
    NotificationSender,
)
from edu_platform.contexts.notification.domain.model import Channel, Notification
from edu_platform.shared_kernel.application import Clock, EventPublisher
from edu_platform.shared_kernel.domain import NotFoundError


class DispatchNotification:
    def __init__(
        self,
        senders: dict[Channel, NotificationSender],
        repo: NotificationRepository,
        publisher: EventPublisher,
        clock: Clock,
    ) -> None:
        self._senders = senders
        self._repo = repo
        self._publisher = publisher
        self._clock = clock

    def execute(self, notification_id: str) -> Notification:
        notification = self._repo.get(notification_id)
        if notification is None:
            raise NotFoundError(f"notification {notification_id} not found")
        for channel in notification.channels:
            sender = self._senders.get(channel)
            if sender is None:
                continue  # TODO: retry/backoff + circuit breaker per provider
            sender.send(notification)
            notification.mark_dispatched(channel, self._clock.now())
        self._repo.save(notification)
        self._publisher.publish(notification.pull_events())
        return notification

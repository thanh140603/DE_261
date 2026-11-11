"""HTTP push sender (BR1).

A provider-neutral webhook: the local stack can receive it with a tiny HTTP
sink; production can put FCM/APNs behind the same ``NotificationSender`` port
without changing the notification use cases.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from edu_platform.contexts.notification.domain.model import Channel, Notification


class WebhookPushSender:
    channel = Channel.PUSH

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout: float = 5.0,
        attempts: int = 3,
    ) -> None:
        self._url = webhook_url
        self._timeout = timeout
        self._attempts = attempts

    def send(self, notification: Notification) -> None:
        payload: dict[str, Any] = {
            "notification_id": notification.id,
            "recipient_id": notification.recipient_id,
            "title": notification.content.title,
            "body": notification.content.body,
            "deep_link": notification.content.deep_link,
            "priority": notification.priority.value,
        }
        body = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                request = urllib.request.Request(
                    self._url,
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    if response.status >= 400:
                        raise RuntimeError(f"push provider returned {response.status}")
                return
            except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as exc:
                last = exc
                if attempt + 1 < self._attempts:
                    time.sleep(0.2 * (2**attempt))
        assert last is not None
        raise last

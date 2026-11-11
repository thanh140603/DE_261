"""SMTP notification sender (BR1).

The local stack can point ``EDU_EMAIL_SMTP_URL`` at Mailpit/MailHog; production
uses the same adapter with a real SMTP relay. Delivery failures are retried a
few times and then surfaced to the consumer, which owns the DLQ decision.
"""

from __future__ import annotations

import smtplib
import time
from collections.abc import Callable
from email.message import EmailMessage
from urllib.parse import unquote, urlparse

from edu_platform.contexts.notification.domain.model import Channel, Notification


class SmtpEmailSender:
    channel = Channel.EMAIL

    def __init__(
        self,
        smtp_url: str,
        *,
        sender: str,
        address_for: Callable[[str], str] | None = None,
        timeout: float = 5.0,
        attempts: int = 3,
    ) -> None:
        self._smtp_url = smtp_url
        self._sender = sender
        self._address_for = address_for or (lambda learner_id: f"{learner_id}@example.edu")
        self._timeout = timeout
        self._attempts = attempts

    def send(self, notification: Notification) -> None:
        message = EmailMessage()
        message["Subject"] = notification.content.title
        message["From"] = self._sender
        message["To"] = self._address_for(notification.recipient_id)
        message.set_content(notification.content.body)
        last: Exception | None = None
        for attempt in range(self._attempts):
            try:
                self._deliver(message)
                return
            except Exception as exc:
                last = exc
                if attempt + 1 < self._attempts:
                    time.sleep(0.2 * (2**attempt))
        assert last is not None
        raise last

    def _deliver(self, message: EmailMessage) -> None:
        parsed = urlparse(self._smtp_url)
        if parsed.scheme not in {"smtp", "smtps"} or not parsed.hostname:
            raise ValueError("EDU_EMAIL_SMTP_URL must be smtp://host:port or smtps://host:port")
        port = parsed.port or (465 if parsed.scheme == "smtps" else 25)
        smtp_cls = smtplib.SMTP_SSL if parsed.scheme == "smtps" else smtplib.SMTP
        with smtp_cls(parsed.hostname, port, timeout=self._timeout) as smtp:
            if parsed.username:
                smtp.login(unquote(parsed.username), unquote(parsed.password or ""))
            smtp.send_message(message)

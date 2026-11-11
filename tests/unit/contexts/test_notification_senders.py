from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.contexts.notification.infrastructure.senders.email_sender import SmtpEmailSender
from edu_platform.contexts.notification.infrastructure.senders.push_sender import (
    WebhookPushSender,
)


def _notification() -> Notification:
    return Notification(
        id="n1",
        recipient_id="l-002",
        dedup_key=DedupKey("l-002", "lms.deadline_approaching.v1", "a1"),
        channels=(Channel.EMAIL, Channel.PUSH),
        priority=Priority.HIGH,
        content=NotificationContent("Due soon", "Submit before the deadline.", "/learner"),
        source_event_id="e1",
        source_event_type="lms.deadline_approaching.v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_smtp_sender_builds_message(monkeypatch) -> None:
    sent: list[object] = []
    sender = SmtpEmailSender(
        "smtp://mailpit:1025", sender="no-reply@edu.local", address_for=lambda _: "a@b.c"
    )
    monkeypatch.setattr(sender, "_deliver", sent.append)
    sender.send(_notification())
    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "a@b.c"  # type: ignore[index]
    assert "Due soon" in message["Subject"]  # type: ignore[index]


def test_push_sender_posts_payload() -> None:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sender = WebhookPushSender(f"http://127.0.0.1:{server.server_port}/push")
        sender.send(_notification())
    finally:
        server.shutdown()
        thread.join(timeout=2)

    assert received[0]["notification_id"] == "n1"
    assert received[0]["recipient_id"] == "l-002"
    assert received[0]["title"] == "Due soon"

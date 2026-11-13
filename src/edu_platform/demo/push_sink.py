"""Tiny local push-provider sink for the BR1 demo.

The production ``WebhookPushSender`` posts JSON to a provider URL. In local
compose this module is that provider: it accepts POST /push and exposes the
received notifications at GET /events, which makes email/push delivery
observable without external credentials.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

_EVENTS: list[dict[str, Any]] = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/push":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400, "invalid JSON")
            return
        _EVENTS.append(payload)
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json({"status": "ok"})
        elif self.path == "/events":
            self._json(_EVENTS)
        else:
            self.send_error(404)

    def _json(self, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return None


def main() -> None:
    port = int(os.getenv("PUSH_SINK_PORT", "8080"))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()

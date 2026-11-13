"""HTTP client for the grading ingestion service (BR3, service mode).

The main API is a backend-for-frontend: CodeLab still calls ``/api/submissions``
but the submission and its grading result are owned by ``grading-ingest``. This
keeps one write path (the service) and lets the demo API run unchanged in
``demo`` mode.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class GradingServiceError(RuntimeError):
    pass


class GradingNotFound(GradingServiceError):
    pass


class GradingUnavailable(GradingServiceError):
    pass


class GradingClient:
    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def submit(self, learner_id: str, assignment_id: str, code: str) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/submissions",
            {"learner_id": learner_id, "assignment_id": assignment_id, "code": code},
        )
        return data if isinstance(data, dict) else {}

    def submission(self, submission_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/submissions/{submission_id}")
        return data if isinstance(data, dict) else {}

    def learner_submissions(self, learner_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/learners/{learner_id}/submissions")
        return data if isinstance(data, list) else []

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=payload,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = _detail(exc)
            if exc.code == 404:
                raise GradingNotFound(detail) from exc
            if exc.code == 422:
                raise GradingServiceError(detail) from exc
            raise GradingUnavailable(detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GradingUnavailable(f"grading service unavailable: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise GradingServiceError("grading service returned invalid JSON") from exc


def _detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read())
        return str(body.get("detail") or exc.reason)
    except Exception:
        return str(exc.reason)

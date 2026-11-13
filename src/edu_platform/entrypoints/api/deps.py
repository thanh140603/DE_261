"""Request-scoped access to the demo platform, the simulator and the service-mode read models."""

from __future__ import annotations

from fastapi import HTTPException, Request

from edu_platform.contexts.notification.application.ports import NotificationRepository
from edu_platform.contexts.recommendation.infrastructure.postgres_enrollment import (
    PostgresEnrollmentRepository,
)
from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator
from edu_platform.entrypoints.api.grading_client import GradingClient
from edu_platform.platform.config import Settings


def platform(request: Request) -> DemoPlatform:
    return request.app.state.platform  # type: ignore[no-any-return]


def simulator(request: Request) -> Simulator:
    return request.app.state.simulator  # type: ignore[no-any-return]


def settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def notification_repo(request: Request) -> NotificationRepository | None:
    """The API's notification read model; None means the in-process demo store."""
    return request.app.state.notification_repo  # type: ignore[no-any-return]


def enrollment_repo(request: Request) -> PostgresEnrollmentRepository | None:
    return request.app.state.enrollment_repo  # type: ignore[no-any-return]


def grading_client(request: Request) -> GradingClient:
    client = request.app.state.grading
    if client is None:
        raise HTTPException(503, "grading service is not configured (EDU_BR13_MODE=demo)")
    return client  # type: ignore[no-any-return]

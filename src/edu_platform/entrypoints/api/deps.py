"""Request-scoped access to the demo platform and simulator."""

from __future__ import annotations

from fastapi import Request

from edu_platform.demo.container import DemoPlatform
from edu_platform.demo.simulator import Simulator


def platform(request: Request) -> DemoPlatform:
    return request.app.state.platform  # type: ignore[no-any-return]


def simulator(request: Request) -> Simulator:
    return request.app.state.simulator  # type: ignore[no-any-return]

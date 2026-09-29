"""SchemaMigrator adapter: chain of per-version upgrade functions.

Each step is a pure function payload -> payload and is applied in order until
CURRENT_SCHEMA_VERSION. Add a step whenever the client contract changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edu_platform.contexts.telemetry.domain.events import CURRENT_SCHEMA_VERSION, SchemaVersion

Step = Callable[[dict[str, Any]], dict[str, Any]]


def migrate_1_0_to_1_1(payload: dict[str, Any]) -> dict[str, Any]:
    """v1.0 clients sent ``ts`` instead of ``occurred_at`` and no ``platform``."""
    out = dict(payload)
    if "occurred_at" not in out and "ts" in out:
        out["occurred_at"] = out.pop("ts")
    out.setdefault("platform", "web")
    out["schema_version"] = "1.1"
    return out


STEPS: dict[SchemaVersion, tuple[SchemaVersion, Step]] = {
    SchemaVersion(1, 0): (SchemaVersion(1, 1), migrate_1_0_to_1_1),
}


class ChainedSchemaMigrator:
    def __init__(
        self, steps: dict[SchemaVersion, tuple[SchemaVersion, Step]] | None = None
    ) -> None:
        self._steps = STEPS if steps is None else steps

    def migrate(self, payload: dict[str, Any], from_version: SchemaVersion) -> dict[str, Any]:
        version = from_version
        while version < CURRENT_SCHEMA_VERSION:
            if version not in self._steps:
                raise ValueError(f"no migration path from schema {version}")
            version, step = self._steps[version]
            payload = step(payload)
        return payload

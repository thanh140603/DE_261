"""Domain event base.

Every event carries:
- event_id      : idempotency key for consumers (dedup in Redis / Kafka EOS).
- event_type    : stable, versioned name (``grading.submission_graded.v1``).
- occurred_at   : event time (NOT processing time) - drives Flink watermarks.
- aggregate_id  : partition key on Kafka so ordering per aggregate is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from edu_platform.shared_kernel.domain.ids import new_id


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    event_type: ClassVar[str] = "shared.domain_event.v1"

    aggregate_id: str
    event_id: str = field(default_factory=new_id)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))

    def to_payload(self) -> dict[str, Any]:
        """Serialisable representation. Adapters are responsible for encoding (JSON/Avro)."""
        from dataclasses import asdict

        payload = asdict(self)
        payload["event_type"] = self.event_type
        payload["occurred_at"] = self.occurred_at.isoformat()
        return payload

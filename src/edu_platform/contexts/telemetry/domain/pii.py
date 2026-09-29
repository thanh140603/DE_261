"""PII handling rules for BR6 (de-identification before analytics).

Domain rule: nothing past bronze may contain a raw learner identifier, email,
IP or device id. Pseudonymisation is deterministic (keyed hash) so joins
across tables still work, but it is not reversible without the key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from edu_platform.shared_kernel.domain import ValueObject


class Pseudonymizer(Protocol):
    """Domain service port. Infrastructure supplies the keyed-hash implementation."""

    def pseudonymize(self, raw_identifier: str) -> str: ...


@dataclass(frozen=True)
class PiiPolicy(ValueObject):
    """Which payload fields must be dropped or hashed before leaving bronze."""

    drop_fields: frozenset[str] = frozenset({"email", "ip_address", "device_id", "full_name"})
    hash_fields: frozenset[str] = frozenset({"learner_id", "user_id"})

    def apply(self, payload: dict[str, Any], pseudonymizer: Pseudonymizer) -> dict[str, Any]:
        cleaned = {k: v for k, v in payload.items() if k not in self.drop_fields}
        for f in self.hash_fields:
            if f in cleaned and cleaned[f] is not None:
                cleaned[f] = pseudonymizer.pseudonymize(str(cleaned[f]))
        return cleaned

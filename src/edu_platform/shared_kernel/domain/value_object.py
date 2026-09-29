"""Value Object base.

Value objects are immutable and compared by value. Subclasses are frozen
dataclasses; put validation in ``__post_init__`` and raise InvariantViolation.

Example::

    @dataclass(frozen=True)
    class RiskScore(ValueObject):
        value: float

        def __post_init__(self) -> None:
            if not 0.0 <= self.value <= 1.0:
                raise InvariantViolation("risk score must be within [0, 1]")
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValueObject:
    """Marker base class. Equality and hashing come from the frozen dataclass."""

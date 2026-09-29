"""Entity base: identity-based equality."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from edu_platform.shared_kernel.domain.ids import new_id

TId = TypeVar("TId")


@dataclass(eq=False)
class Entity(Generic[TId]):
    id: TId = field(default_factory=lambda: new_id())  # type: ignore[assignment]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash((type(self), self.id))

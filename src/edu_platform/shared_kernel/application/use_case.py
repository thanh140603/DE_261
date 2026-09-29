"""Use-case (application service) contract.

One class per business operation, a single ``execute`` method, dependencies
injected through the constructor. Keeps handlers small (SRP) and easily
composed by entrypoints.
"""

from __future__ import annotations

from typing import Generic, Protocol, TypeVar

TCommand = TypeVar("TCommand", contravariant=True)
TResult = TypeVar("TResult", covariant=True)


class UseCase(Protocol, Generic[TCommand, TResult]):
    def execute(self, command: TCommand) -> TResult: ...

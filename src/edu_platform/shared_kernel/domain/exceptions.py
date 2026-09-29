class DomainError(Exception):
    """Base class for all business-rule failures. Never wrap infrastructure errors in it."""


class InvariantViolation(DomainError):
    """An aggregate would enter an invalid state."""


class NotFoundError(DomainError):
    """A referenced aggregate does not exist."""

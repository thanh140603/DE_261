"""Strongly-typed identifiers.

Using distinct NewTypes (instead of bare ``str``) lets mypy catch a LearnerId
being passed where a CourseId is expected, which is a common bug class in
wide analytical joins.
"""

from __future__ import annotations

import uuid
from typing import NewType

LearnerId = NewType("LearnerId", str)
CourseId = NewType("CourseId", str)
OrganisationId = NewType("OrganisationId", str)
AssignmentId = NewType("AssignmentId", str)
SubmissionId = NewType("SubmissionId", str)
ContentId = NewType("ContentId", str)
SessionId = NewType("SessionId", str)


def new_id() -> str:
    """Generate a globally unique id (UUID4). Centralised so it can be swapped for ULID later."""
    return str(uuid.uuid4())

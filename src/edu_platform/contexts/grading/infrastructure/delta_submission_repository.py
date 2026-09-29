"""SubmissionRepository adapter backed by Delta (silver.submissions) with a
Redis read-through for hot lookups by the grading-ingestion service.

Content (TODO): MERGE on submission_id; store ExecutionResult.tests as array<struct>
so the BR4 mart can explode per test case.
"""

from __future__ import annotations

# TODO

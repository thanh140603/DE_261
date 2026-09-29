"""Use case BR4: pass rate per test case per assignment, anomaly flag."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from edu_platform.contexts.analytics.domain.anomaly_policy import AssessmentAnomalyPolicy
from edu_platform.contexts.analytics.domain.model import AssessmentItemStats, TimeWindow
from edu_platform.contexts.grading.domain.model import Submission, TestStatus
from edu_platform.shared_kernel.domain.ids import AssignmentId


class BuildAssessmentMart:
    def __init__(self, policy: AssessmentAnomalyPolicy) -> None:
        self._policy = policy

    def execute(
        self, submissions: list[Submission], window: TimeWindow
    ) -> list[AssessmentItemStats]:
        attempts: dict[tuple[str, str], int] = defaultdict(int)
        passes: dict[tuple[str, str], int] = defaultdict(int)
        for s in submissions:
            if s.result is None or s.submitted_at is None:
                continue
            if not (window.start <= s.submitted_at <= window.end):
                continue
            for t in s.result.tests:
                key = (s.assignment_id, t.test_case_id)
                attempts[key] += 1
                passes[key] += t.status is TestStatus.PASSED
        rates = {k: passes[k] / attempts[k] for k in attempts}
        per_assignment: dict[str, list[float]] = defaultdict(list)
        for (assignment_id, _), rate in rates.items():
            per_assignment[assignment_id].append(rate)
        out: list[AssessmentItemStats] = []
        for (assignment_id, item_id), rate in rates.items():
            med = median(per_assignment[assignment_id])
            out.append(
                AssessmentItemStats(
                    assignment_id=AssignmentId(assignment_id),
                    item_id=item_id,
                    attempts=attempts[(assignment_id, item_id)],
                    passes=passes[(assignment_id, item_id)],
                    pass_rate=round(rate, 3),
                    assignment_median_pass_rate=round(med, 3),
                    is_anomalous=self._policy.is_anomalous(
                        attempts[(assignment_id, item_id)], rate, med
                    ),
                    window=window,
                )
            )
        return sorted(out, key=lambda r: (r.assignment_id, r.item_id))

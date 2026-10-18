"""Warehouse vocabulary and parameters must not drift from the domain they implement."""

from __future__ import annotations

import re
from pathlib import Path

from edu_platform.contexts.analytics.application.build_video_heatmap import _KIND
from edu_platform.contexts.analytics.domain.engagement_policy import (
    _VERB_TO_WEIGHT,
    DEFAULT_DECLINE_RATIO,
)
from edu_platform.contexts.analytics.domain.model import (
    AnomalyThreshold,
    EngagementWeights,
    MinCohortPolicy,
)
from edu_platform.contexts.risk.domain.model import SlidingWindowPolicy
from edu_platform.contexts.telemetry.domain.events import Verb
from edu_platform.entrypoints.batch.warehouse_job import policy_params

WAREHOUSE = Path(__file__).resolve().parents[3] / "warehouse"
ROW = re.compile(r"\('(\w+)',\s*'(\w+)',\s*(NULL|'\w+'),\s*(CAST\(NULL AS STRING\)|NULL|'\w+')")


def _dim_activity() -> dict[str, tuple[str | None, str | None]]:
    rows = ROW.findall((WAREHOUSE / "transform/gold/dim_activity.sql").read_text())

    def val(v: str) -> str | None:
        return None if "NULL" in v else v.strip("'")

    return {verb: (val(eng), val(video)) for verb, _group, eng, video in rows}


def test_dim_activity_covers_exactly_the_verb_vocabulary() -> None:
    assert set(_dim_activity()) == {v.value for v in Verb}


def test_engagement_categories_match_engagement_policy() -> None:
    for verb, (category, _) in _dim_activity().items():
        assert category == _VERB_TO_WEIGHT.get(verb), verb


def test_video_interactions_match_heatmap_use_case() -> None:
    expected = {verb.value: kind for verb, kind in _KIND.items()}
    assert {v: k for v, (_, k) in _dim_activity().items() if k} == expected


def test_policy_params_come_from_domain_value_objects() -> None:
    params = policy_params()
    assert params["anomaly_min_attempts"] == AnomalyThreshold().min_attempts
    assert params["anomaly_max_pass_rate"] == AnomalyThreshold().max_pass_rate
    assert params["anomaly_min_delta"] == AnomalyThreshold().min_delta_from_median
    assert params["min_cohort_k"] == MinCohortPolicy().k
    assert params["w_attempt"] == EngagementWeights().attempt
    assert params["decline_ratio"] == DEFAULT_DECLINE_RATIO
    assert params["risk_alert_threshold"] == SlidingWindowPolicy().alert_threshold

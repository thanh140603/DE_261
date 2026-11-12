from datetime import UTC, datetime, timedelta

from edu_platform.br45.effectiveness import metrics
from edu_platform.br45.oracle import windows


def test_window_oracle_deduplicates_retracts_and_excludes_upper_boundary():
    end = datetime(2026, 11, 1, tzinfo=UTC)
    event = {
        "event_id": "one",
        "student_id": "s",
        "course_id": "c",
        "event_time": end - timedelta(days=7),
        "delta": 1,
    }
    events = [
        event,
        event,
        {**event, "event_id": "undo", "delta": -1},
        {**event, "event_id": "future", "event_time": end},
        {**event, "event_id": "inside", "event_time": end - timedelta(seconds=1)},
    ]
    assert windows(events, [end]) == {("s", "c", end): 1}


def test_average_precision_groups_ties_without_label_order_bias():
    rows = [
        {"label": 1, "score": 50, "lead_days": 10},
        {"label": 0, "score": 50, "lead_days": None},
    ]
    result = metrics(rows, "score", 50)
    assert result == metrics(list(reversed(rows)), "score", 50)
    assert result["pr_auc_average_precision"] == 0.5
    assert result["precision"] == 0.5
    assert result["recall"] == 1
    assert result["median_lead_days"] == 10


def test_no_predicted_positives_has_defined_zero_precision():
    result = metrics([{"label": 1, "score": 0, "lead_days": 5}], "score", 60)
    assert result["precision"] == result["recall"] == result["f1"] == 0
    assert result["median_lead_days"] is None

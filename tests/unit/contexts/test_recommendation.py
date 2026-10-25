from __future__ import annotations

from edu_platform.contexts.recommendation.domain.next_step_policy import CourseRef, NextStepPolicy


def _course(course_id: str, difficulty: str, category: str = "c") -> CourseRef:
    return CourseRef(course_id, f"Title {course_id}", difficulty, category)


def _catalogue() -> list[CourseRef]:
    return [
        _course("e1", "easy"),
        _course("e2", "easy"),
        _course("m1", "medium"),
        _course("m2", "medium"),
        _course("h1", "hard"),
    ]


def test_next_course_to_enroll_is_none_when_all_enrolled() -> None:
    policy = NextStepPolicy()
    assert policy.next_course_to_enroll(_catalogue(), ["e1", "e2", "m1", "m2", "h1"], []) is None


def test_suggest_starts_with_easy_when_nothing_completed() -> None:
    policy = NextStepPolicy()
    order = [r.course_id for r in policy.suggest_courses(_catalogue(), [], [])]
    assert order[:2] == ["e1", "e2"]  # easy first, title order
    assert set(order[2:]) == {"m1", "m2", "h1"}  # everything else is discouraged


def test_suggest_prioritizes_next_difficulty_after_easy() -> None:
    policy = NextStepPolicy()
    order = [r.course_id for r in policy.suggest_courses(_catalogue(), ["e1"], ["e1"])]
    assert order == ["m1", "m2", "e2", "h1"]


def test_suggest_prioritizes_hard_after_medium() -> None:
    policy = NextStepPolicy()
    order = [r.course_id for r in policy.suggest_courses(_catalogue(), ["e1", "m1"], ["e1", "m1"])]
    assert order[0] == "h1"


def test_same_family_medium_before_new_family_and_too_advanced() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("c1", "easy", "math"),
        _course("c2", "easy", "history"),
        _course("m1", "medium", "math"),
        _course("m2", "medium", "history"),
    ]
    # completed easy math: continue math at medium, then start history at easy,
    # then (last) the too-advanced history medium.
    order = [r.course_id for r in policy.suggest_courses(catalogue, ["c1"], ["c1"])]
    assert order == ["m1", "c2", "m2"]


def test_next_course_to_enroll_is_top_suggestion() -> None:
    policy = NextStepPolicy()
    suggestions = policy.suggest_courses(_catalogue(), ["e1"], ["e1"])
    top = policy.next_course_to_enroll(_catalogue(), ["e1"], ["e1"])
    assert top is not None and top.course_id == suggestions[0].course_id


def test_suggest_excludes_enrolled() -> None:
    policy = NextStepPolicy()
    ids = [r.course_id for r in policy.suggest_courses(_catalogue(), ["e1", "m1"], [])]
    assert "e1" not in ids and "m1" not in ids


def test_related_category_beats_unrelated_at_same_level() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("ai", "easy", "artificial intelligence"),
        _course("ml", "medium", "machine learning"),
        _course("cloud", "medium", "cloud"),
        _course("de", "medium", "data engineering"),
    ]
    # completed Introduction to AI -> the related ML medium ranks before cloud/DE
    order = [r.course_id for r in policy.suggest_courses(catalogue, ["ai"], ["ai"])]
    assert order[0] == "ml"


def test_relatedness_anchors_on_most_recent_completed_course() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("sql", "easy", "database"),
        _course("ai", "easy", "artificial intelligence"),
        _course("ml", "medium", "machine learning"),
        _course("dl", "hard", "deep learning"),
        _course("de", "hard", "data engineering"),
    ]
    # completed SQL (data) earlier, then AI (ai), then ML (ai): current track is ai
    order = [
        r.course_id
        for r in policy.suggest_courses(catalogue, ["sql", "ai", "ml"], ["sql", "ai", "ml"])
    ]
    assert order[0] == "dl"  # ai-family hard first
    assert order[1] == "de"  # data-family hard after — not "related" to the current track


def test_medium_data_before_hard_data_when_data_frontier_is_easy() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("sql", "easy", "database"),
        _course("ai", "easy", "artificial intelligence"),
        _course("ml", "medium", "machine learning"),
        _course("cloud", "medium", "cloud"),
        _course("de", "hard", "data engineering"),
        _course("mleng", "hard", "machine learning"),
    ]
    # completed SQL (easy data), AI (easy ai), ML (medium ai).
    # The data family is only at easy, so the medium cloud must come before the
    # hard data engineering course (which would be a skip within the data family).
    order = [
        r.course_id
        for r in policy.suggest_courses(catalogue, ["sql", "ai", "ml"], ["sql", "ai", "ml"])
    ]
    assert order.index("mleng") < order.index("cloud")  # related ai hard first
    assert order.index("cloud") < order.index("de")  # medium data before hard data


def test_skip_gap_recommends_the_missing_medium() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("ai", "easy", "artificial intelligence"),
        _course("ml", "medium", "machine learning"),
        _course("cv", "hard", "computer vision"),
        _course("cloud", "medium", "cloud"),
    ]
    # completed AI (easy) and CV (hard), skipping ML (medium): the gap must be
    # filled before jumping to another track.
    order = [r.course_id for r in policy.suggest_courses(catalogue, ["ai", "cv"], ["ai", "cv"])]
    assert order[0] == "ml"


def test_current_track_broaden_beats_different_track_next_step() -> None:
    policy = NextStepPolicy()
    catalogue = [
        _course("sql", "easy", "database"),
        _course("py", "easy", "programming"),
        _course("ai", "easy", "artificial intelligence"),
        _course("cv", "hard", "computer vision"),
        _course("de", "medium", "data engineering"),
        _course("ml", "medium", "machine learning"),
        _course("mleng", "hard", "machine learning"),
        _course("streamde", "hard", "data engineering"),
    ]
    # completed SQL, Python, AI, CV, DE(medium), ML(medium); current track is AI.
    enrolled = ["sql", "py", "ai", "cv", "de", "ml"]
    completed = ["sql", "py", "ai", "cv", "de", "ml"]
    order = [r.course_id for r in policy.suggest_courses(catalogue, enrolled, completed)]
    # broaden in the current AI track (mleng) before next-step in the data track
    assert order.index("mleng") < order.index("streamde")

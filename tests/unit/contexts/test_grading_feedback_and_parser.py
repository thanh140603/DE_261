from __future__ import annotations

from edu_platform.contexts.grading.domain.feedback_policy import FeedbackPolicy
from edu_platform.contexts.grading.domain.model import Language, TestStatus
from edu_platform.contexts.grading.infrastructure.sandbox_log_parser import SandboxLogParser

RAW_LOG = {
    "stdout": "",
    "stderr": "Traceback...\nNameError: name 'totl' is not defined",
    "exit_code": 1,
    "exec_time_ms": 12,
    "max_rss_kb": 9000,
    "assertions": [
        {"test_case_id": "t1", "status": "passed", "expected": "6", "actual": "6"},
        {"test_case_id": "t2", "status": "failed", "expected": "0", "actual": "1"},
        {"test_case_id": "t3", "status": "error", "expected": "0", "actual": "NameError: totl"},
    ],
}


def test_parser_builds_diffs_and_pass_rate() -> None:
    result = SandboxLogParser().parse(RAW_LOG)
    assert result.pass_rate == 1 / 3
    failed = next(t for t in result.tests if t.test_case_id == "t2")
    assert failed.status is TestStatus.FAILED and "-0" in failed.diff and "+1" in failed.diff


def test_feedback_summary_and_hints() -> None:
    feedback = FeedbackPolicy().build(SandboxLogParser().parse(RAW_LOG), Language.PYTHON)
    assert feedback.summary.startswith("1/3 tests passed")
    assert "1 raised an error" in feedback.summary
    assert any("before it is defined" in h for h in feedback.hints)
    assert feedback.stderr_excerpt is not None and "NameError" in feedback.stderr_excerpt


def test_feedback_timeout_hint() -> None:
    result = SandboxLogParser().parse({"timed_out": True, "exec_time_ms": 3000})
    feedback = FeedbackPolicy().build(result)
    assert any("infinite loop" in h for h in feedback.hints)

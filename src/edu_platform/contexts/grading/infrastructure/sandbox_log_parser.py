"""SandboxResultParser adapter for the execution worker's JSON log.

Maps worker fields (stdout, stderr, exec_time_ms, max_rss_kb, assertions[]) to
ExecutionResult / TestCaseResult and precomputes unified diffs so feedback
rendering never needs the raw log again. Tolerates partial logs (timeout/OOM).
Contract: /schemas/grading/v1/sandbox_result.schema.json
"""

from __future__ import annotations

import difflib
from typing import Any

from edu_platform.contexts.grading.domain.model import ExecutionResult, TestCaseResult, TestStatus


class SandboxLogParser:
    def parse(self, raw_log: dict[str, Any]) -> ExecutionResult:
        tests: list[TestCaseResult] = []
        for a in raw_log.get("assertions") or []:
            status = TestStatus(a.get("status", "error"))
            expected = _text(a.get("expected"))
            actual = _text(a.get("actual"))
            diff = None
            if status is TestStatus.FAILED and expected is not None and actual is not None:
                diff = "\n".join(
                    difflib.unified_diff(
                        expected.splitlines(),
                        actual.splitlines(),
                        "expected",
                        "actual",
                        lineterm="",
                    )
                )
            tests.append(
                TestCaseResult(
                    test_case_id=str(a.get("test_case_id", "?")),
                    status=status,
                    expected=expected,
                    actual=actual,
                    diff=diff,
                    duration_ms=int(a.get("duration_ms", 0)),
                )
            )
        if raw_log.get("timed_out") and not tests:
            tests.append(TestCaseResult("execution", TestStatus.TIMEOUT))
        return ExecutionResult(
            stdout=str(raw_log.get("stdout", ""))[:4000],
            stderr=str(raw_log.get("stderr", ""))[:4000],
            runtime_ms=max(0, int(raw_log.get("exec_time_ms", 0))),
            memory_kb=max(0, int(raw_log.get("max_rss_kb", 0))),
            exit_code=int(raw_log.get("exit_code", 1)),
            tests=tuple(tests),
        )


def _text(value: Any) -> str | None:
    return None if value is None else str(value)

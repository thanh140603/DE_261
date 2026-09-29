"""Domain service: derive learner-facing Feedback from an ExecutionResult (BR3).

Pure function, no I/O. Language hints are a small heuristic table; a richer
hint engine can replace this class behind the same interface.
"""

from __future__ import annotations

from .model import ExecutionResult, Feedback, Language, TestStatus

_HINTS: dict[Language, list[tuple[str, str]]] = {
    Language.PYTHON: [
        ("NameError", "A name is used before it is defined. Check spelling and the function name."),
        ("TypeError", "A value has the wrong type. Check what your function returns."),
        ("IndentationError", "Indentation is inconsistent. Use 4 spaces per level."),
        ("SyntaxError", "Python could not parse the code. Look at the line in the error."),
        ("RecursionError", "The function calls itself without a base case."),
    ],
    Language.SQL: [
        ("no such column", "A column name does not exist. Check the table definitions."),
        ("no such table", "The table name is wrong. Check the schema in the assignment."),
        ("syntax error", "SQL could not be parsed. Check commas, keywords and quotes."),
        ("GROUP BY", "Aggregates need every non-aggregated column in GROUP BY."),
    ],
}


class FeedbackPolicy:
    def __init__(self, stderr_lines: int = 8) -> None:
        self._stderr_lines = stderr_lines

    def build(self, result: ExecutionResult, language: Language = Language.PYTHON) -> Feedback:
        failed = tuple(t for t in result.tests if t.status is not TestStatus.PASSED)
        passed = len(result.tests) - len(failed)
        timeouts = sum(t.status is TestStatus.TIMEOUT for t in failed)
        errors = sum(t.status is TestStatus.ERROR for t in failed)

        if not result.tests:
            summary = "No tests could run. The code did not execute successfully."
        elif not failed:
            summary = f"All {passed} tests passed in {result.runtime_ms} ms."
        else:
            parts = [f"{passed}/{len(result.tests)} tests passed"]
            if timeouts:
                parts.append(f"{timeouts} timed out")
            if errors:
                parts.append(f"{errors} raised an error")
            summary = ", ".join(parts) + "."

        stderr_excerpt = None
        if result.stderr.strip():
            stderr_excerpt = "\n".join(result.stderr.strip().splitlines()[-self._stderr_lines :])

        hints: list[str] = []
        haystack = result.stderr + "\n".join((t.actual or "") for t in failed)
        for needle, hint in _HINTS.get(language, []):
            if needle.lower() in haystack.lower() and hint not in hints:
                hints.append(hint)
        if failed and not hints and any(t.diff for t in failed):
            hints.append("Compare expected and actual output in the failed tests below.")
        if timeouts:
            hints.append(
                "Look for an infinite loop or an algorithm that is too slow for large inputs."
            )
        return Feedback(
            summary=summary, failed_tests=failed, stderr_excerpt=stderr_excerpt, hints=tuple(hints)
        )

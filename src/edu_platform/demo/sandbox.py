"""Demo sandbox execution worker (stands in for the isolated grading workers).

Python code runs in a separate interpreter process (``-I`` isolated mode, hard
timeout); SQL runs against an in-memory SQLite database in query-only mode.
Output follows /schemas/grading/v1/sandbox_result.schema.json so the grading
context parses it exactly like a production worker log.

Not a security boundary: the production worker runs in a locked-down container.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from typing import Any

from edu_platform.demo.seed import SQL_FIXTURES, SQL_SCHEMA, Assignment
from edu_platform.shared_kernel.domain.ids import new_id

_HARNESS = r"""
import json, sys, time, traceback
spec = json.load(sys.stdin)
ns = {}
results = []
try:
    exec(compile(spec["code"], "submission.py", "exec"), ns)
    ok = True
except BaseException:
    traceback.print_exc()
    ok = False
for t in spec["tests"]:
    t0 = time.perf_counter()
    if not ok:
        results.append({"test_case_id": t["id"], "status": "error", "expected": t["expected"], "actual": "code did not load", "duration_ms": 0})
        continue
    try:
        actual = repr(eval(t["call"], ns))
        status = "passed" if actual == t["expected"] else "failed"
    except BaseException as exc:
        actual, status = f"{type(exc).__name__}: {exc}", "error"
    results.append({"test_case_id": t["id"], "status": status, "expected": t["expected"], "actual": actual,
                    "duration_ms": int((time.perf_counter() - t0) * 1000)})
sys.stdout.write("\n__RESULTS__" + json.dumps(results))
"""


class DemoSandboxWorker:
    def __init__(self, timeout_sec: float = 3.0) -> None:
        self._timeout = timeout_sec

    def run(self, submission_id: str, assignment: Assignment, code: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        if assignment.language == "sql":
            log = self._run_sql(assignment, code)
        else:
            log = self._run_python(assignment, code)
        log.update(
            submission_id=submission_id,
            worker_run_id=new_id(),
            exec_time_ms=int((time.perf_counter() - t0) * 1000),
        )
        log.setdefault("max_rss_kb", 0)
        return log

    def _run_python(self, assignment: Assignment, code: str) -> dict[str, Any]:
        spec = {
            "code": code,
            "tests": [
                {"id": t.id, "call": t.call, "expected": t.expected} for t in assignment.tests
            ],
        }
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-S", "-c", _HARNESS],
                input=json.dumps(spec),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "stdout": (exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else "",
                "stderr": "Execution exceeded the time limit.",
                "exit_code": 124,
                "timed_out": True,
                "assertions": [
                    {
                        "test_case_id": t.id,
                        "status": "timeout",
                        "expected": t.expected,
                        "actual": None,
                    }
                    for t in assignment.tests
                ],
            }
        stdout, _, results = proc.stdout.rpartition("\n__RESULTS__")
        assertions = json.loads(results) if results else []
        return {
            "stdout": stdout[:2000],
            "stderr": proc.stderr[-2000:],
            "exit_code": proc.returncode,
            "timed_out": False,
            "assertions": assertions,
        }

    def _run_sql(self, assignment: Assignment, code: str) -> dict[str, Any]:
        assertions: list[dict[str, Any]] = []
        stderr = ""
        for t in assignment.tests:
            conn = sqlite3.connect(":memory:")
            try:
                conn.executescript(SQL_SCHEMA + SQL_FIXTURES[t.call])
                conn.execute("PRAGMA query_only = 1")
                deadline = time.perf_counter() + self._timeout

                def _abort_if_slow(d: float = deadline) -> int:
                    return 1 if time.perf_counter() > d else 0

                conn.set_progress_handler(_abort_if_slow, 1000)
                t0 = time.perf_counter()
                rows = conn.execute(code).fetchall()
                actual = repr([tuple(r) for r in rows])
                status = "passed" if actual == t.expected else "failed"
            except sqlite3.Error as exc:
                actual, status = f"{type(exc).__name__}: {exc}", "error"
                stderr = str(exc)
                t0 = time.perf_counter()
            finally:
                conn.close()
            assertions.append(
                {
                    "test_case_id": t.id,
                    "status": status,
                    "expected": t.expected,
                    "actual": actual,
                    "duration_ms": int((time.perf_counter() - t0) * 1000),
                }
            )
        return {
            "stdout": "",
            "stderr": stderr,
            "exit_code": 0 if not stderr else 1,
            "timed_out": False,
            "assertions": assertions,
        }

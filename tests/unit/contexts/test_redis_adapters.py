"""Tests for the Redis-backed BR1/BR3 adapters against an in-process fake.

The adapters are written against a minimal Redis client interface, so these
tests need no real Redis: they inject ``FakeRedis`` and assert the exact
commands' semantics (SET NX, sorted-set rate limiting, list inbox, sets).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from edu_platform.contexts.grading.domain.model import (
    ExecutionResult,
    Feedback,
    Language,
    Submission,
    SubmissionStatus,
    TestCaseResult,
    TestStatus,
)
from edu_platform.contexts.grading.infrastructure.redis_repository import (
    RedisCodeStore,
    RedisSubmissionRepository,
)
from edu_platform.contexts.notification.domain.model import (
    Channel,
    DedupKey,
    Notification,
    NotificationContent,
    Priority,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_repository import (
    RedisNotificationRepository,
)
from edu_platform.contexts.notification.infrastructure.redis_notification_state import (
    RedisNotificationState,
)
from edu_platform.shared_kernel.domain.ids import AssignmentId, LearnerId, SubmissionId


class FakeRedis:
    def __init__(self) -> None:
        self.strings: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.zsets: dict[str, dict[str, float]] = {}

    def set(self, name: str, value: Any, ex: int | None = None, nx: bool = False) -> bool | None:
        if nx and name in self.strings:
            return None
        self.strings[name] = str(value)
        return True

    def get(self, name: str) -> str | None:
        return self.strings.get(name)

    def sadd(self, name: str, *values: str) -> int:
        self.sets.setdefault(name, set()).update(values)
        return len(values)

    def smembers(self, name: str) -> set[str]:
        return set(self.sets.get(name, set()))

    def sismember(self, name: str, value: str) -> bool:
        return value in self.sets.get(name, set())

    def exists(self, name: str) -> bool:
        return name in self.strings

    def delete(self, name: str) -> bool:
        return self.strings.pop(name, None) is not None

    def lpush(self, name: str, *values: str) -> int:
        for value in reversed(values):
            self.lists.setdefault(name, []).insert(0, value)
        return len(self.lists[name])

    def ltrim(self, name: str, start: int, stop: int) -> bool:
        if name in self.lists:
            self.lists[name] = self.lists[name][start : stop + 1]
        return True

    def lrange(self, name: str, start: int, end: int) -> list[str]:
        return list(self.lists.get(name, []))[start : end + 1 if end != -1 else None]

    def incr(self, name: str) -> int:
        self.strings[name] = str(int(self.strings.get(name, "0")) + 1)
        return int(self.strings[name])

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(name, {}).update(mapping)
        return len(mapping)

    def zcard(self, name: str) -> int:
        return len(self.zsets.get(name, {}))

    def zremrangebyscore(self, name: str, minimum: float, maximum: float) -> int:
        removed = 0
        for member in list(self.zsets.get(name, {})):
            score = self.zsets[name][member]
            if minimum <= score <= maximum:
                del self.zsets[name][member]
                removed += 1
        return removed

    def expire(self, name: str, seconds: int) -> bool:
        return True


def _notification(notification_id: str = "n1", recipient: str = "l-002") -> Notification:
    return Notification(
        id=notification_id,
        recipient_id=recipient,
        dedup_key=DedupKey(recipient, "lms.deadline_approaching.v1", "a-py-even"),
        channels=(Channel.IN_APP,),
        priority=Priority.HIGH,
        content=NotificationContent("Due soon", "Submit before the deadline."),
        source_event_id="e1",
        source_event_type="lms.deadline_approaching.v1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_notification_state_dedup_is_atomic_nx() -> None:
    state = RedisNotificationState(FakeRedis())
    key = DedupKey("l-002", "lms.deadline_approaching.v1", "a-py-even")
    assert state.seen_before(key, 60) is False
    assert state.seen_before(key, 60) is True


def test_notification_state_rate_limit_enforced() -> None:
    state = RedisNotificationState(FakeRedis())
    results = [state.within_rate_limit("l-002", 5, 3600) for _ in range(6)]
    assert results == [True, True, True, True, True, False]


def test_notification_state_opt_out() -> None:
    client = FakeRedis()
    state = RedisNotificationState(client)
    assert state.opted_out("l-002", Channel.EMAIL) is False
    client.sadd("edu:notif:optout:l-002", Channel.EMAIL.value)
    assert state.opted_out("l-002", Channel.EMAIL) is True


def test_notification_repository_round_trip_and_inbox() -> None:
    repo = RedisNotificationRepository(FakeRedis())
    repo.save(_notification())
    got = repo.get("n1")
    assert got is not None and got.recipient_id == "l-002"
    assert [n.id for n in repo.for_recipient("l-002")] == ["n1"]
    assert repo.count() == 1


def test_submission_repository_round_trip_and_grading() -> None:
    repo = RedisSubmissionRepository(FakeRedis())
    submission = Submission.receive(
        submission_id=SubmissionId("s1"),
        learner_id=LearnerId("l-002"),
        assignment_id=AssignmentId("a-py-even"),
        language=Language.PYTHON,
        code_ref="code/s1",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        attempt_number=1,
    )
    repo.save(submission)
    got = repo.get(SubmissionId("s1"))
    assert got is not None and got.status is SubmissionStatus.QUEUED
    assert [s.id for s in repo.for_learner(LearnerId("l-002"))] == ["s1"]
    assert len(repo.all()) == 1

    submission.grade(
        ExecutionResult(
            stdout="",
            stderr="",
            runtime_ms=10,
            memory_kb=100,
            exit_code=0,
            tests=(TestCaseResult("t1", TestStatus.PASSED, duration_ms=1),),
        ),
        Feedback("All good", tuple(), None),
    )
    repo.save(submission)
    graded = repo.get(SubmissionId("s1"))
    assert graded is not None and graded.status is SubmissionStatus.GRADED
    assert graded.result is not None and graded.result.pass_rate == 1.0


def test_code_store_put_and_get() -> None:
    store = RedisCodeStore(FakeRedis())
    ref = store.put(SubmissionId("s1"), "print(1)")
    assert store.get(ref) == "print(1)"

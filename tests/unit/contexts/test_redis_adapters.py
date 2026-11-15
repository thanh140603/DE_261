"""Tests for the Redis-backed BR1/BR3 adapters against an in-process fake.

The adapters are written against a minimal Redis client interface, so these
tests need no real Redis: they inject ``FakeRedis`` and assert the exact
commands' semantics (SET NX, sorted-set rate limiting, list inbox, sets).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
        self.pttls: dict[str, int] = {}

    def set(
        self,
        name: str,
        value: Any,
        ex: int | None = None,
        px: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and name in self.strings:
            return None
        self.strings[name] = str(value)
        if px is not None:
            self.pttls[name] = px
        elif ex is not None:
            self.pttls[name] = ex * 1000
        return True

    def pttl(self, name: str) -> int:
        return self.pttls.get(name, -2) if name in self.strings else -2

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

    def delete(self, *names: str) -> bool:
        removed = False
        for name in names:
            for store in (self.strings, self.sets, self.lists, self.zsets, self.pttls):
                if name in store:
                    store.pop(name)
                    removed = True
        return removed

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

    def lrem(self, name: str, count: int, value: str) -> int:
        rows = self.lists.get(name, [])
        kept = [row for row in rows if row != value]
        self.lists[name] = kept
        return len(rows) - len(kept)

    def rpush(self, name: str, *values: str) -> int:
        self.lists.setdefault(name, []).extend(values)
        return len(self.lists[name])

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.strings.get(key) for key in keys]

    def incr(self, name: str) -> int:
        self.strings[name] = str(int(self.strings.get(name, "0")) + 1)
        return int(self.strings[name])

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self.zsets.setdefault(name, {}).update(mapping)
        return len(mapping)

    def zcard(self, name: str) -> int:
        return len(self.zsets.get(name, {}))

    def zrevrange(self, name: str, start: int, stop: int) -> list[str]:
        rows = sorted(self.zsets.get(name, {}).items(), key=lambda item: item[1], reverse=True)
        members = [member for member, _ in rows]
        return members[start:] if stop == -1 else members[start : stop + 1]

    def zcount(self, name: str, minimum: str | float, maximum: str | float) -> int:
        def parse(bound: str | float, *, upper: bool) -> tuple[float, bool]:
            if bound == "+inf":
                return float("inf"), False
            if bound == "-inf":
                return float("-inf"), False
            if isinstance(bound, str) and bound.startswith("("):
                return float(bound[1:]), True
            return float(bound), False

        low, low_exclusive = parse(minimum, upper=False)
        high, high_exclusive = parse(maximum, upper=True)
        count = 0
        for score in self.zsets.get(name, {}).values():
            above = score > low if low_exclusive else score >= low
            below = score < high if high_exclusive else score <= high
            count += int(above and below)
        return count

    def zremrangebyrank(self, name: str, start: int, stop: int) -> int:
        rows = sorted(self.zsets.get(name, {}).items(), key=lambda item: item[1])
        keep = rows[:start] if stop == -1 else rows[:start] + rows[stop + 1 :]
        before = len(rows)
        self.zsets[name] = dict(keep)
        return before - len(keep)

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


def _notification(
    notification_id: str = "n1",
    recipient: str = "l-002",
    created_at: datetime = datetime(2026, 1, 1, tzinfo=UTC),
) -> Notification:
    return Notification(
        id=notification_id,
        recipient_id=recipient,
        dedup_key=DedupKey(recipient, "lms.deadline_approaching.v1", "a-py-even"),
        channels=(Channel.IN_APP,),
        priority=Priority.HIGH,
        content=NotificationContent("Due soon", "Submit before the deadline."),
        source_event_id="e1",
        source_event_type="lms.deadline_approaching.v1",
        created_at=created_at,
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


def test_notification_repository_save_is_idempotent_and_updates_dispatch() -> None:
    """RouteEvent saves, then DispatchNotification saves again to persist delivery."""
    client = FakeRedis()
    repo = RedisNotificationRepository(client)
    notification = _notification()

    repo.save(notification)
    notification.mark_dispatched(Channel.IN_APP, datetime(2026, 1, 1, tzinfo=UTC))
    repo.save(notification)

    assert [n.id for n in repo.for_recipient("l-002")] == ["n1"]
    assert client.lists["edu:notif:inbox:l-002"] == ["n1"]
    assert client.strings["edu:notif:count"] == "1"
    restored = repo.get("n1")
    assert restored is not None
    assert Channel.IN_APP in restored.dispatched


def test_submission_repository_round_trip_and_grading() -> None:
    repo = RedisSubmissionRepository(FakeRedis())
    submission = Submission.receive(
        submission_id=SubmissionId("s1"),
        learner_id=LearnerId("l-002"),
        assignment_id=AssignmentId("a-py-even"),
        language=Language.PYTHON,
        code_ref="code/s1",
        submitted_at=datetime.now(tz=UTC) - timedelta(minutes=5),
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


def test_notification_repository_pages_and_counts_unread() -> None:
    repo = RedisNotificationRepository(FakeRedis())
    repo.save(_notification("n1", created_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC)))
    repo.save(_notification("n2", created_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC)))
    repo.save(_notification("n3", created_at=datetime(2026, 1, 1, 0, 2, tzinfo=UTC)))

    assert [n.id for n in repo.for_recipient("l-002", limit=2)] == ["n3", "n2"]
    assert [n.id for n in repo.for_recipient("l-002")] == ["n3", "n2", "n1"]
    since = datetime(2026, 1, 1, 0, 1, tzinfo=UTC)
    assert repo.count_since("l-002", since) == 1
    assert repo.for_recipient("l-002", limit=0) == []


def test_notification_repository_backfills_timeline_for_legacy_inbox() -> None:
    client = FakeRedis()
    repo = RedisNotificationRepository(client)
    repo.save(_notification("n1"))
    client.zsets.clear()  # an inbox written before the sorted set existed

    assert [n.id for n in repo.for_recipient("l-002", limit=1)] == ["n1"]


def test_submission_repository_attempt_counter_and_paging() -> None:
    repo = RedisSubmissionRepository(FakeRedis())
    learner = LearnerId("l-002")
    assert repo.next_attempt(learner, "a-py-even") == 1
    first = Submission.receive(
        submission_id=SubmissionId("s1"),
        learner_id=learner,
        assignment_id=AssignmentId("a-py-even"),
        language=Language.PYTHON,
        code_ref="code/s1",
        submitted_at=datetime.now(tz=UTC) - timedelta(hours=2),
        attempt_number=1,
    )
    repo.save(first)
    assert repo.next_attempt(learner, "a-py-even") == 2
    second = Submission.receive(
        submission_id=SubmissionId("s2"),
        learner_id=learner,
        assignment_id=AssignmentId("a-py-even"),
        language=Language.PYTHON,
        code_ref="code/s2",
        submitted_at=datetime.now(tz=UTC) - timedelta(hours=1),
        attempt_number=2,
    )
    repo.save(second)

    assert [s.id for s in repo.for_learner(learner, limit=1)] == ["s2"]
    assert [s.id for s in repo.for_learner(learner)] == ["s2", "s1"]

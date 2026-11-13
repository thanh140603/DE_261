"""Composition root of the demo: every bounded context wired to in-memory
adapters and to the in-process event bus. The consumers registered in
demo/handlers.py are the same handlers the production services and Flink
jobs would run against Kafka.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from edu_platform.contexts.analytics.application.build_assessment_mart import BuildAssessmentMart
from edu_platform.contexts.analytics.application.build_org_progress_report import (
    BuildOrgProgressReport,
)
from edu_platform.contexts.analytics.application.build_video_heatmap import BuildVideoHeatmap
from edu_platform.contexts.analytics.application.compute_engagement_trend import (
    ComputeEngagementTrend,
)
from edu_platform.contexts.analytics.domain.anomaly_policy import AssessmentAnomalyPolicy
from edu_platform.contexts.analytics.domain.engagement_policy import EngagementPolicy
from edu_platform.contexts.analytics.domain.model import (
    AnomalyThreshold,
    EngagementWeights,
    MinCohortPolicy,
)
from edu_platform.contexts.content.application.publish_content_version import (
    PublishContentVersion,
)
from edu_platform.contexts.content.domain.model import ContentItem, ContentType
from edu_platform.contexts.content.infrastructure.in_memory import (
    InMemoryCacheInvalidator,
    InMemoryContentRepository,
    InMemoryDocumentStore,
    InMemorySearchIndexer,
    InMemoryVectorIndex,
)
from edu_platform.contexts.grading.application.enqueue_submission import EnqueueSubmission
from edu_platform.contexts.grading.application.normalize_execution_log import (
    NormalizeExecutionLog,
    NormalizeExecutionLogCommand,
)
from edu_platform.contexts.grading.domain.feedback_policy import FeedbackPolicy
from edu_platform.contexts.grading.domain.model import Submission
from edu_platform.contexts.grading.infrastructure.in_memory import (
    CallbackSubmissionQueue,
    InMemoryCodeStore,
    InMemorySubmissionRepository,
)
from edu_platform.contexts.grading.infrastructure.sandbox_log_parser import SandboxLogParser
from edu_platform.contexts.notification.application.dispatch_notification import (
    DispatchNotification,
)
from edu_platform.contexts.notification.application.ports import NotificationSender
from edu_platform.contexts.notification.application.route_event import RouteEvent
from edu_platform.contexts.notification.domain.model import Channel, RateLimitPolicy
from edu_platform.contexts.notification.domain.rule_engine import RuleEngine
from edu_platform.contexts.notification.infrastructure.in_memory import (
    CallableAudienceResolver,
    FormatTemplateRenderer,
    InMemoryNotificationRepository,
    InMemoryNotificationState,
    RecordingSender,
)
from edu_platform.contexts.notification.infrastructure.yaml_rule_repository import (
    YamlRuleRepository,
)
from edu_platform.contexts.recommendation.application.compute_batch_features import (
    ComputeBatchFeatures,
    ComputeBatchFeaturesCommand,
    GradedFact,
)
from edu_platform.contexts.recommendation.application.compute_session_features import (
    SessionFeaturePolicy,
)
from edu_platform.contexts.recommendation.application.load_learner_features import (
    LoadLearnerFeatures,
)
from edu_platform.contexts.recommendation.domain.next_step_policy import NextStepPolicy
from edu_platform.contexts.recommendation.infrastructure.in_memory import InMemoryOnlineFeatureStore
from edu_platform.contexts.recommendation.infrastructure.redis_online_store import (
    RedisOnlineFeatureStore,
)
from edu_platform.contexts.risk.application.score_learner_risk import ScoreLearnerRisk
from edu_platform.contexts.risk.domain.model import SlidingWindowPolicy
from edu_platform.contexts.risk.domain.scoring_policy import RiskScoringPolicy
from edu_platform.contexts.risk.domain.signal_rules import SignalRules
from edu_platform.contexts.risk.infrastructure.in_memory import (
    InMemoryRiskProfileRepository,
    InMemoryRiskScoreStore,
)
from edu_platform.contexts.telemetry.application.normalize_events import NormalizeEvents
from edu_platform.contexts.telemetry.domain.pii import PiiPolicy
from edu_platform.contexts.telemetry.infrastructure.hmac_pseudonymizer import HmacPseudonymizer
from edu_platform.contexts.telemetry.infrastructure.in_memory import (
    InMemoryBronze,
    InMemoryDeadLetter,
    InMemorySilver,
)
from edu_platform.contexts.telemetry.infrastructure.schema_migrations import (
    ChainedSchemaMigrator,
)
from edu_platform.contexts.telemetry.infrastructure.validator import LearningEventValidator
from edu_platform.demo import seed
from edu_platform.demo.event_bus import InMemoryEventBus
from edu_platform.demo.sandbox import DemoSandboxWorker
from edu_platform.demo.sse import Broadcaster
from edu_platform.platform.clock import SystemClock
from edu_platform.platform.logging import get_logger
from edu_platform.platform.messaging.kafka_producer import KafkaEventPublisher
from edu_platform.platform.messaging.topics import Topic
from edu_platform.platform.storage.redis_client import create_redis_client
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId

log = get_logger(__name__)


class DemoPlatform:
    """Holds every adapter and use case for the single-process demo.

    ``service_mode`` keeps the in-process adapters for the pipeline UI but adds a
    Kafka publisher so simulator events can drive the real BR1/BR2/BR3 services.
    """

    def __init__(
        self,
        rules_path: Path,
        pii_secret: bytes = b"demo-secret",
        *,
        service_mode: bool = False,
        kafka_bootstrap: str = "localhost:9092",
        redis_url: str = "redis://localhost:6379/0",
    ) -> None:
        self.clock = SystemClock()
        self.bus = InMemoryEventBus()
        self.broadcaster = Broadcaster()
        self.started_at = datetime.now(tz=UTC)
        self.service_mode = service_mode
        self.publisher = (
            KafkaEventPublisher(kafka_bootstrap, client_id="edu-demo-simulator")
            if service_mode
            else None
        )

        # telemetry (BR6 medallion)
        self.bronze = InMemoryBronze()
        self.silver = InMemorySilver()
        self.dlq = InMemoryDeadLetter()
        self.pseudonymizer = HmacPseudonymizer(pii_secret)
        self.normalize = NormalizeEvents(
            LearningEventValidator(),
            ChainedSchemaMigrator(),
            self.pseudonymizer,
            PiiPolicy(),
            self.silver,
            self.dlq,
        )
        self.late_events = 0

        # grading (BR3)
        self.submissions = InMemorySubmissionRepository()
        self.code_store = InMemoryCodeStore()
        self.sandbox = DemoSandboxWorker()
        self.pending_synthetic_log: dict[str, Any] | None = None
        self.queue = CallbackSubmissionQueue(self._run_sandbox)
        self.enqueue_submission = EnqueueSubmission(
            self.submissions, self.queue, self.code_store, self.bus
        )
        self.grade_submission = NormalizeExecutionLog(
            self.submissions, SandboxLogParser(), FeedbackPolicy(), self.bus
        )

        # risk (BR5)
        self.risk_policy = SlidingWindowPolicy(cooldown=timedelta(minutes=2))
        self.risk_repo = InMemoryRiskProfileRepository()
        self.risk_store = InMemoryRiskScoreStore()
        self.signal_rules = SignalRules()
        self.score_risk = ScoreLearnerRisk(
            self.risk_repo, RiskScoringPolicy(), self.risk_policy, self.risk_store, self.bus
        )
        self.risk_alerts: list[dict[str, Any]] = []

        # recommendation (BR2: rules + optional two-branch feature context)
        self.next_step = NextStepPolicy()
        self.enrollments: dict[str, list[str]] = {
            it.id: list(it.course_ids) for it in seed.LEARNERS
        }
        self.completed_courses: dict[str, list[str]] = {it.id: [] for it in seed.LEARNERS}
        self.feature_store = (
            RedisOnlineFeatureStore(create_redis_client(redis_url))
            if service_mode
            else InMemoryOnlineFeatureStore()
        )
        self.load_features = LoadLearnerFeatures(self.feature_store)
        self.compute_batch = ComputeBatchFeatures(self.feature_store)
        self.session_policy = SessionFeaturePolicy()

        # notification (BR1)
        rules = YamlRuleRepository(rules_path).all()
        self.notifications = InMemoryNotificationRepository()
        self.notification_state = InMemoryNotificationState(self.clock.now)
        self.senders: dict[Channel, NotificationSender] = {c: RecordingSender(c) for c in Channel}
        audience = CallableAudienceResolver(
            # Live view: enrolling through the UI must affect the next notification.
            lambda course_id: [
                learner.id
                for learner in seed.LEARNERS
                if course_id in self.enrollments.get(learner.id, [])
            ],
            lambda learner_id: next(
                (it.advisor_id for it in seed.LEARNERS if it.id == learner_id), None
            ),
        )
        self.route_event = RouteEvent(
            RuleEngine(rules),
            audience,
            self.notification_state,
            FormatTemplateRenderer(),
            self.notifications,
            RateLimitPolicy(),
            self.bus,
            self.clock,
        )
        self.dispatch = DispatchNotification(self.senders, self.notifications, self.bus, self.clock)
        self.suppressed_count = 0
        self.last_route_result: dict[str, Any] = {"created": 0, "suppressed": []}

        # content (BR8)
        self.content = InMemoryContentRepository()
        self.cache = InMemoryCacheInvalidator()
        self.vectors = InMemoryVectorIndex()
        self.search = InMemorySearchIndexer()
        self.publish_content = PublishContentVersion(
            self.content, InMemoryDocumentStore(), self.cache, self.vectors, self.search, self.bus
        )
        for course in seed.COURSES:
            for lesson in course.lessons:
                self.content.save(
                    ContentItem(
                        id=ContentId(lesson.content_id),
                        course_id=CourseId(course.id),
                        content_type=ContentType.VIDEO_TRANSCRIPT,
                        title=lesson.title,
                    )
                )

        # analytics (BR4, BR6, BR7, BR8)
        self.assessment_mart = BuildAssessmentMart(
            AssessmentAnomalyPolicy(AnomalyThreshold(min_attempts=10))
        )
        self.video_heatmap = BuildVideoHeatmap()
        self.org_report = BuildOrgProgressReport(MinCohortPolicy(5))
        self.engagement = ComputeEngagementTrend(EngagementPolicy(EngagementWeights()))

    # -- feature branches (BR2) --------------------------------------------------
    def refresh_features(self) -> None:
        """Demo mode: compute both branches in-process so the UI has real features.

        Service mode is fed by the batch materialisation job and the session
        streaming job; recomputing here would create a second writer.
        """
        if self.service_mode:
            return
        self._refresh_longterm()
        for pseudonym in {event.learner_pseudonym for event in self.silver.all()}:
            self.update_session(pseudonym)

    def _refresh_longterm(self) -> None:
        if self.service_mode:
            return
        graded = [
            GradedFact(
                learner_pseudonym=self.pseudonym(str(s.learner_id)),
                course_id=seed.assignment(s.assignment_id).course_id,
                pass_rate=s.result.pass_rate,
                at=s.submitted_at,
            )
            for s in self.submissions.all()
            if s.result is not None
        ]
        self.compute_batch.execute(
            ComputeBatchFeaturesCommand(
                as_of=datetime.now(tz=UTC),
                events=self.silver.all(),
                graded=graded,
                lessons_per_course={c.id: len(c.lessons) for c in seed.COURSES},
                course_skill={c.id: c.skill for c in seed.COURSES},
            )
        )

    def update_session(self, learner_pseudonym: str) -> None:
        if self.service_mode:
            return
        events = [
            event for event in self.silver.all() if event.learner_pseudonym == learner_pseudonym
        ]
        features = self.session_policy.compute(events)
        if features is not None:
            self.feature_store.put_session(features)

    # -- Kafka bridge used by the simulator (service mode only) -----------------
    def publish_raw(self, topic: str, *, key: str | None, payload: dict[str, Any]) -> None:
        if self.publisher is None:
            return
        try:
            self.publisher.publish_raw(topic, key=key, payload=payload)
        except Exception as exc:  # a broker outage must not break the demo UI
            log.warning("demo kafka publish failed", topic=topic, error=str(exc))

    def close(self) -> None:
        if self.publisher is not None:
            self.publisher.close()

    # -- grading queue consumer ------------------------------------------------
    def _run_sandbox(self, submission: Submission) -> None:
        """Run the worker (or replay a synthetic log) and grade the submission."""
        log = self.pending_synthetic_log
        self.pending_synthetic_log = None
        if log is None:
            code = self.code_store.get(submission.code_ref)
            log = self.sandbox.run(submission.id, seed.assignment(submission.assignment_id), code)
        self.bus.emit(
            Topic.SANDBOX_RESULT_RAW,
            key=submission.id,
            event_type="grading.sandbox_result.raw.v1",
            payload={"submission_id": submission.id, "tests": len(log.get("assertions", []))},
        )
        self.grade_submission.execute(
            NormalizeExecutionLogCommand(submission.id, str(log["worker_run_id"]), log)
        )
        self._refresh_longterm()

    # -- helpers used by handlers and the API ---------------------------------
    def pseudonym(self, learner_id: str) -> str:
        return self.pseudonymizer.pseudonymize(learner_id)

    def learner_by_pseudonym(self) -> dict[str, str]:
        return {self.pseudonym(it.id): it.id for it in seed.LEARNERS}

    def enroll(self, learner_id: str, course_id: str) -> None:
        enrolled = self.enrollments[learner_id]
        if course_id not in enrolled:
            enrolled.append(course_id)

    def complete_course(self, learner_id: str, course_id: str) -> None:
        if course_id not in self.completed_courses[learner_id]:
            self.completed_courses[learner_id].append(course_id)

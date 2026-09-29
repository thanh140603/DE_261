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
    FormatTemplateRenderer,
    InMemoryNotificationRepository,
    InMemoryNotificationState,
    RecordingSender,
    StaticAudienceResolver,
)
from edu_platform.contexts.notification.infrastructure.yaml_rule_repository import (
    YamlRuleRepository,
)
from edu_platform.contexts.recommendation.application.compute_batch_features import (
    ComputeBatchFeatures,
)
from edu_platform.contexts.recommendation.application.compute_session_features import (
    ComputeSessionFeatures,
)
from edu_platform.contexts.recommendation.domain.next_step_policy import NextStepPolicy
from edu_platform.contexts.recommendation.infrastructure.in_memory import (
    InMemoryOnlineFeatureStore,
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
from edu_platform.platform.messaging.topics import Topic
from edu_platform.shared_kernel.domain.ids import ContentId, CourseId


class DemoPlatform:
    """Holds every adapter and use case for the single-process demo."""

    def __init__(self, rules_path: Path, pii_secret: bytes = b"demo-secret") -> None:
        self.clock = SystemClock()
        self.bus = InMemoryEventBus()
        self.broadcaster = Broadcaster()
        self.started_at = datetime.now(tz=UTC)

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

        # recommendation (BR2)
        self.online_features = InMemoryOnlineFeatureStore()
        self.session_features = ComputeSessionFeatures(self.online_features)
        self.batch_features = ComputeBatchFeatures(self.online_features)
        self.next_step = NextStepPolicy()

        # notification (BR1)
        rules = YamlRuleRepository(rules_path).all()
        self.notifications = InMemoryNotificationRepository()
        self.notification_state = InMemoryNotificationState(self.clock.now)
        self.senders: dict[Channel, NotificationSender] = {c: RecordingSender(c) for c in Channel}
        audience = StaticAudienceResolver(
            {c.id: [it.id for it in seed.LEARNERS if c.id in it.course_ids] for c in seed.COURSES},
            {it.id: it.advisor_id for it in seed.LEARNERS},
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

    # -- helpers used by handlers and the API ---------------------------------
    def pseudonym(self, learner_id: str) -> str:
        return self.pseudonymizer.pseudonymize(learner_id)

    def learner_by_pseudonym(self) -> dict[str, str]:
        return {self.pseudonym(it.id): it.id for it in seed.LEARNERS}

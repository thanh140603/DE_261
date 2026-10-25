// Types mirror docs/api.md exactly.

export interface Organisation { id: string; name: string }
export interface Lesson { id: string; title: string; content_id: string; duration_sec: number }
export interface Course { id: string; title: string; org_id: string; skill: string; lessons: Lesson[] }
export interface Learner { id: string; name: string; org_id: string; course_ids: string[]; advisor_id: string }
export interface Assignment {
  id: string; title: string; course_id: string; language: "python" | "sql";
  prompt: string; starter_code: string; test_case_ids: string[];
}
export interface Advisor { id: string; name: string }
export interface Overview {
  organisations: Organisation[]; courses: Course[]; learners: Learner[];
  assignments: Assignment[]; advisors: Advisor[];
}

export interface Stats {
  bronze: number; silver: number; dlq: number; late_events: number;
  topics: Record<string, number>; notifications_sent: number; notifications_suppressed: number;
  submissions_graded: number; risk_alerts: number; feature_rows: number;
  content_versions: number; last_event_at: string | null;
}

export interface SseMessage { type: string; at: string; payload: Record<string, unknown> }

export interface SimStatus { running: boolean; rate_per_sec: number; generated: number }
export interface TelemetryInput {
  learner_id: string; verb: string; course_id?: string; content_id?: string;
  video_position_sec?: number; platform?: string; late_seconds?: number;
  schema_version?: "1.0" | "1.1"; malformed?: boolean;
}
export interface TelemetryResult { event_id: string; outcome: "silver" | "dlq"; reason?: string }
export interface BurstResult { generated: number; silver: number; dlq: number }
export interface LmsEventInput {
  event_type: "assignment_created" | "deadline_approaching" | "course_updated";
  course_id: string; assignment_id?: string; hours_to_deadline?: number; title?: string;
}
export interface LmsEventResult {
  event_id: string;
  notifications: { created: number; suppressed: { learner_id: string; reason: string }[] };
}
export interface CdcInput {
  table: "lesson_progress" | "enrollments" | "grades"; learner_id: string; course_id: string;
  lesson_id?: string; percent_done?: number; status?: string; score?: number;
}
export interface CdcResult {
  applied: boolean;
  risk?: { learner_id: string; course_id: string; score: number; alerted: boolean };
}
export interface ScenarioResult { name: string; steps: { at: string; message: string }[]; outcome: Record<string, unknown> }

export interface TopicSummary { topic: string; count: number; last_at: string | null }
export interface TopicMessage { key: string; event_type: string; at: string; payload: Record<string, unknown> }
export interface DlqRecord { event_id: string; reason: string; at: string; payload: Record<string, unknown> }
export interface LearningEvent {
  event_id: string; learner_pseudonym: string; course_id: string; content_id: string | null;
  session_id: string; verb: string; platform: string; occurred_at: string; received_at: string;
  lateness_seconds: number; video_position_sec: number | null; schema_version: string; late: boolean;
}

export interface Notification {
  id: string; title: string; body: string; channels: string[]; priority: string;
  created_at: string; source_event_type: string; deep_link: string | null;
}
export interface LongtermFeatures {
  completion_rate_30d: number; avg_pass_rate_30d: number; active_days_30d: number;
  preferred_platform: string; skill_mastery: Record<string, number>;
}
export interface SessionFeatures {
  session_id: string; active_minutes: number; events_in_session: number; last_verbs: string[];
  current_course_id: string | null; struggle_score: number; updated_at: string;
}
export interface Recommendations {
  next_step: { course_id: string; title: string; difficulty: string; category: string; score: number; reason: string } | null;
  enrolled: { course_id: string; title: string; difficulty: string; category: string; completed: boolean }[];
  courses: { course_id: string; title: string; difficulty: string; category: string; score: number; reason: string }[];
}

export interface TestResult {
  test_case_id: string; status: "passed" | "failed" | "error" | "timeout";
  expected: string | null; actual: string | null; diff: string | null; duration_ms: number;
}
export interface Submission {
  id: string; learner_id: string; assignment_id: string; language: string;
  status: "queued" | "running" | "graded" | "failed"; attempt_number: number; submitted_at: string;
  result: {
    stdout?: string; stderr: string; runtime_ms: number; memory_kb: number; exit_code: number;
    pass_rate: number; tests: TestResult[];
  } | null;
  feedback: { summary: string; failed_tests: TestResult[]; stderr_excerpt: string | null; hints: string[] } | null;
}

export interface AssessmentRow {
  assignment_id: string; assignment_title: string; item_id: string; attempts: number; passes: number;
  pass_rate: number; assignment_median_pass_rate: number; is_anomalous: boolean;
}
export interface Heatmap {
  content_id: string; title: string; duration_sec: number;
  buckets: { second: number; play: number; pause: number; seek: number; learners: number }[];
}
export interface Engagement {
  windows: { start: string; end: string }[];
  learners: { pseudonym: string; scores: number[]; declining: boolean }[];
  course_avg: number[];
}
export interface ContentRecord {
  id: string; course_id: string; title: string; content_type: string;
  versions: { number: number; published_at: string; checksum: string }[];
  indexed_version: number | null; chunk_count: number;
  cache_state: "warm" | "invalidated"; search_version: number | null;
}
export interface PublishResult {
  version: number; sync: { step: string; status: "done" | "skipped"; ms: number }[]; notifications_created: number;
}

export interface RiskAlert {
  learner_id: string; learner_name: string; course_id: string; course_title: string;
  score: number; top_signals: string[]; at: string;
}
export interface RiskDetail {
  learner_id: string;
  courses: {
    course_id: string; score: number; computed_at: string;
    signals: { kind: string; weight: number; observed_at: string }[];
    history: { at: string; score: number }[]; last_alert_at: string | null;
  }[];
  policy: { window_days: number; slide_days: number; alert_threshold: number; cooldown_days: number };
}

export interface OrgProgress {
  organisation_id: string; as_of: string; min_cohort: number;
  rows: {
    course_id: string; course_title: string; skill: string; cohort_size: number;
    completion_rate: number | null; avg_mastery: number | null; suppressed: boolean;
  }[];
}

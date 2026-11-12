export interface Page<T> { items: T[]; total: number; offset: number; limit: number; window_start?: string; window_end?: string;
  materialization_status?: string; computed_at?: string; engine?: string; error?: string; stale?: boolean;
  publication_id?: string; published_revision?: string; pending_revision?: string; source_delta_version?: number }
export interface AnalyticsSession { id: string; role: string; courses: { id: string; title: string }[]; replay?: boolean; classroom?: boolean }
export interface AnalyticsSession { id: string; role: string; courses: { id: string; title: string }[]; replay?: boolean; classroom?: boolean }
export interface AssessmentStat {
  id: string; course_id: string; assignment_id: string; question_id: string; question_version: number;
  question_title?: string; assignment_title?: string; test_case_id?: string; test_case_version?: number;
  total_valid_evaluations: number; passed_evaluations: number; failed_evaluations: number;
  unique_students: number; invalid_evaluations: number; infrastructure_errors: number;
  pass_rate: number | null; first_attempt_pass_rate?: number | null; latest_attempt_pass_rate?: number | null;
  state: string; severity: string; reasons: string[]; previous_pass_rate: number | null;
  threshold: number; minimum_students: number; window_start: string; window_end: string; computed_at: string;
  cohort_students?: number; cohort_attempts?: number; cohort_pass_rate?: number | null; cohort_definition?: string;
}
export interface RiskReason { signal: string; reason: string; points: number }
export interface StudentRisk {
  student_id: string; student_name?: string; course_id: string; score: number; level: string; eligible: boolean;
  eligibility_reason: string; evaluated_at: string; computed_at?: string; reasons: RiskReason[];
  policy_version?: number;
  policy: { alert_threshold: number; slide_seconds: number; allowed_lateness_days: number; version?: number };
  features: { activity_7d: number; activity_previous_7d: number; activity_14d: number;
    last_activity_at: string | null; inactivity_days: number | null; due_assignments_14d: number;
    missed_deadlines_14d: number; submission_rate_14d: number | null; telemetry_available: boolean };
}
export interface DropoutAlert {
  id: string; student_id: string; course_id: string; score: number; level: string; reasons: RiskReason[];
  status: "NEW" | "ACKNOWLEDGED" | "RESOLVED"; evaluated_at: string; created_at: string;
  acknowledged_at: string | null; resolved_at: string | null;
}
export interface InterventionNote {
  id: number; alert_id: string; actor: string; action: string; note: string; created_at: string;
}
export interface RiskPolicy {
  inactivity_points: number; missed_points: number; completion_points: number; decline_points: number;
  medium_threshold: number; high_threshold: number; critical_threshold: number; alert_threshold: number;
  cooldown_hours: number; minimum_reference_events: number;
}
export interface CoursePolicy { course_id: string; version: number; parameters: RiskPolicy; effective_after: string | null }
export type RiskPage = Page<StudentRisk> & { summary: { monitored: number; levels: Record<string, number> } };

export interface ReplayStatus {
  revision: number; stage: number; stage_count: number; label: string; updated_at: string; next_update_at: string;
}
interface BenchmarkGroup { records: number; runs: number; correct_runs: number }
export interface EngineBenchmarkRow {
  engine: "postgres" | "spark" | "flink";
  phase: "processing" | "e2e_correction" | "e2e_alert" | "e2e_recovery";
  records: number;
  planned: number;
  statuses: Record<string, number>;
  median_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
  median_events_per_second: number | null;
}
export interface EngineBenchmarkComparison {
  processing: EngineBenchmarkRow[];
  end_to_end: EngineBenchmarkRow[];
  metadata: {
    engine: EngineBenchmarkRow["engine"];
    engine_version: string | null;
    checks: { phase: string; status: string; error?: string }[];
  }[];
}
export interface ReplayBenchmarks {
  br4: (BenchmarkGroup & { sql_ms: number; python_ms: number; persisted_refresh_ms: number; query_ms: number; correction_refresh_ms: number })[];
  br5: (BenchmarkGroup & { kafka_to_persisted_windows_ms: number; unique_events_per_second: number; python_batch_ms: number })[];
  cdc_to_alert_ms: number;
  cdc_measured_at: string;
  engine_comparison?: { br4: EngineBenchmarkComparison; br5: EngineBenchmarkComparison } | null;
}

// BR6/BR7/BR8: lakehouse marts served through Trino.
export interface LakehouseSession extends AnalyticsSession { organisations: { id: string; name: string }[] }
export interface SkillProgress {
  organisation_id: string; organisation_name: string | null; as_of: string; built_at: string; min_cohort: number;
  rows: { course_id: string; course_title: string | null; skill: string | null; cohort_size: number;
    completion_rate: number | null; avg_mastery: number | null; completed_learners: number | null; suppressed: boolean }[];
}
export interface VideoEntry { content_id: string; title: string | null; versions: { version: number | null; duration_sec: number | null }[] }
export interface VideoHeatmap {
  video: { content_id: string; version: number | null; title: string | null; course_id: string | null; duration_sec: number | null };
  as_of: string; window_days: number; built_at: string; versions: VideoEntry["versions"];
  seconds: { second: number; play: number; pause: number; seek: number; learners: number; intensity: number }[];
  live: { days: string[]; updated_at: string | null; seconds: { second: number; play: number; pause: number; seek: number; learners: number }[] } | null;
}
export interface EngagementTrend {
  course_id: string; as_of: string; built_at: string; decline_ratio: number; declining_count: number;
  week_starts: string[]; course_avg: number[];
  learners: { learner_pseudonym: string; scores: number[]; deltas: (number | null)[]; declining: boolean }[];
  live: { day: string; updated_at: string | null; scores: Record<string, number>; course_avg: number | null } | null;
}
export type Filters = Record<string, string | number | undefined>;
export interface TimelineEvent { id: string; kind: string; occurred_at: string; data: { event_type?: string; execution_status?: string; note?: string; actor?: string; action?: string; assignment_id?: string } }
export interface Diagnostics { state: { key: string; value: Record<string, unknown>; updated_at: string }[]; invalid_records: number; outbox_pending: number }

// BR8: content sync (LMS row + versioned object -> CDC -> cache, vectors, search).
export interface ContentStatus {
  content_id: string; course_id: string; content_type: string; title: string; version: number; object_key: string;
  duration_sec: number | null; updated_at: string; indexed_version: number | null; indexed_at: string | null;
  chunk_count: number; cache_state: "warm" | "invalidated"; in_sync: boolean;
}
export interface ContentDocument { content_id: string; course_id: string; title: string; version: number; body: string; cache: "hit" | "miss" }
export type PublishedVersion = Omit<ContentStatus, "indexed_version" | "indexed_at" | "chunk_count" | "cache_state" | "in_sync"> & { changed: boolean; status: "pending_sync" | "unchanged" };
export interface SearchHit { content_id: string; version: number; title: string; ordinal: number; section_path: string[]; snippet: string; score: number }

export function analyticsApi(token: string) {
  async function request<T>(path: string, filters: Filters = {}, method = "GET", body?: unknown): Promise<T> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") query.set(key, String(value));
    const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetch(`/api${path}?${query}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (!response.ok) {
      const body: { detail?: unknown } = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}); check the filters and retry.`);
    }
    if (!(response.headers.get("content-type") ?? "").includes("json")) {
      // an older server answers unknown API paths with the web app itself
      throw new Error("This server does not provide this report yet. Rebuild and restart the demo service to get the latest API.");
    }
    return response.json() as Promise<T>;
  }
  return {
    session: () => request<AnalyticsSession>("/analytics/session"),
    diagnostics: () => request<Diagnostics>("/analytics/diagnostics"),
    refresh: (course: string, start?: string, end?: string) => request<{ id: string; status: string }>(`/instructor/courses/${encodeURIComponent(course)}/assessment-jobs`, {}, "POST", { start, end }),
    replayStatus: () => request<ReplayStatus>("/analytics/replay"),
    advanceReplay: (revision: number) => request<ReplayStatus>("/analytics/replay/advance", {}, "POST", { revision }),
    replayBenchmarks: () => request<ReplayBenchmarks>("/analytics/replay/benchmarks"),
    questions: (course: string, filters: Filters) => request<Page<AssessmentStat>>(`/instructor/courses/${encodeURIComponent(course)}/questions/statistics`, filters),
    cases: (question: string, filters: Filters) => request<Page<AssessmentStat>>(`/instructor/questions/${encodeURIComponent(question)}/test-cases`, filters),
    risks: (course: string, filters: Filters) => request<RiskPage>(`/advisor/courses/${encodeURIComponent(course)}/at-risk-students`, filters),
    history: (student: string, filters: Filters) => request<Page<StudentRisk>>(`/advisor/students/${encodeURIComponent(student)}/risk-history`, filters),
    student: (student: string, filters: Filters) => request<{ student_id: string; courses: StudentRisk[] }>(`/advisor/students/${encodeURIComponent(student)}/risk`, filters),
    coursePolicy: (course: string) => request<CoursePolicy>(`/advisor/courses/${encodeURIComponent(course)}/policy`),
    updatePolicy: (course: string, expected_version: number, parameters: RiskPolicy) =>
      request<CoursePolicy>(`/advisor/courses/${encodeURIComponent(course)}/policy`, {}, "PUT", { expected_version, parameters }),
    notes: (id: string) => request<InterventionNote[]>(`/advisor/alerts/${encodeURIComponent(id)}/notes`),
    addNote: (id: string, note: string, idempotency_key: string) =>
      request<InterventionNote>(`/advisor/alerts/${encodeURIComponent(id)}/notes`, {}, "POST", { note, idempotency_key }),
    alerts: (filters: Filters) => request<Page<DropoutAlert>>("/advisor/alerts", filters),
    lakehouseSession: () => request<LakehouseSession>("/lakehouse/session"),
    skillProgress: (org: string, filters: Filters) => request<SkillProgress>(`/admin/organisations/${encodeURIComponent(org)}/skill-progress`, filters),
    courseVideos: (course: string) => request<{ course_id: string; videos: VideoEntry[] }>(`/instructor/courses/${encodeURIComponent(course)}/videos`),
    heatmap: (content: string, filters: Filters) => request<VideoHeatmap>(`/instructor/videos/${encodeURIComponent(content)}/interaction-heatmap`, filters),
    engagementTrend: (course: string, filters: Filters) => request<EngagementTrend>(`/instructor/courses/${encodeURIComponent(course)}/engagement-trend`, filters),
    courseContent: (course: string) => request<{ course_id: string; items: ContentStatus[] }>(`/instructor/courses/${encodeURIComponent(course)}/content`),
    contentDocument: (content: string) => request<ContentDocument>(`/instructor/content/${encodeURIComponent(content)}/document`),
    publishVersion: (content: string, body: string, title?: string) => request<PublishedVersion>(`/instructor/content/${encodeURIComponent(content)}/versions`, {}, "POST", { body, title: title || undefined }),
    search: (course: string, q: string, mode: "keyword" | "hybrid") => request<{ hits: SearchHit[] }>(`/instructor/courses/${encodeURIComponent(course)}/search`, { q, mode, limit: 8 }),
    timeline: (student: string, course: string) => request<Page<TimelineEvent>>(`/advisor/students/${encodeURIComponent(student)}/timeline`, { course_id: course, limit: 50 }),
    alertAction: (id: string, action: "acknowledge" | "resolve", note = "") => request<DropoutAlert>(`/advisor/alerts/${encodeURIComponent(id)}/${action}`, {}, "PATCH", { note }),
  };
}

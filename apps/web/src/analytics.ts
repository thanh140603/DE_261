export interface Page<T> { items: T[]; total: number; offset: number; limit: number; window_start?: string; window_end?: string }
export interface AnalyticsSession { id: string; role: string; courses: { id: string; title: string }[] }
export interface AssessmentStat {
  id: string; course_id: string; assignment_id: string; question_id: string; question_version: number;
  question_title?: string; assignment_title?: string; test_case_id?: string; test_case_version?: number;
  total_valid_evaluations: number; passed_evaluations: number; failed_evaluations: number;
  unique_students: number; invalid_evaluations: number; infrastructure_errors: number;
  pass_rate: number | null; first_attempt_pass_rate?: number | null; latest_attempt_pass_rate?: number | null;
  state: string; severity: string; reasons: string[]; previous_pass_rate: number | null;
  threshold: number; minimum_students: number; window_start: string; window_end: string; computed_at: string;
}
export interface RiskReason { signal: string; reason: string; points: number }
export interface StudentRisk {
  student_id: string; course_id: string; score: number; level: string; eligible: boolean;
  eligibility_reason: string; evaluated_at: string; computed_at?: string; reasons: RiskReason[];
  policy: { alert_threshold: number; slide_seconds: number; allowed_lateness_days: number };
  features: { activity_7d: number; activity_previous_7d: number; activity_14d: number;
    last_activity_at: string | null; inactivity_days: number | null; due_assignments_14d: number;
    missed_deadlines_14d: number; submission_rate_14d: number | null; telemetry_available: boolean };
}
export interface DropoutAlert {
  id: string; student_id: string; course_id: string; score: number; level: string; reasons: RiskReason[];
  status: "NEW" | "ACKNOWLEDGED" | "RESOLVED"; evaluated_at: string; created_at: string;
  acknowledged_at: string | null; resolved_at: string | null;
}
export type RiskPage = Page<StudentRisk> & { summary: { monitored: number; levels: Record<string, number> } };
export type Filters = Record<string, string | number | undefined>;

export function analyticsApi(token: string) {
  async function request<T>(path: string, filters: Filters = {}, method = "GET"): Promise<T> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== "") query.set(key, String(value));
    const response = await fetch(`/api${path}?${query}`, { method, headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) {
      const body: { detail?: unknown } = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${response.status}); check the filters and retry.`);
    }
    return response.json() as Promise<T>;
  }
  return {
    session: () => request<AnalyticsSession>("/analytics/session"),
    questions: (course: string, filters: Filters) => request<Page<AssessmentStat>>(`/instructor/courses/${encodeURIComponent(course)}/questions/statistics`, filters),
    cases: (question: string, filters: Filters) => request<Page<AssessmentStat>>(`/instructor/questions/${encodeURIComponent(question)}/test-cases`, filters),
    risks: (course: string, filters: Filters) => request<RiskPage>(`/advisor/courses/${encodeURIComponent(course)}/at-risk-students`, filters),
    history: (student: string, filters: Filters) => request<Page<StudentRisk>>(`/advisor/students/${encodeURIComponent(student)}/risk-history`, filters),
    student: (student: string, filters: Filters) => request<{ student_id: string; courses: StudentRisk[] }>(`/advisor/students/${encodeURIComponent(student)}/risk`, filters),
    alerts: (filters: Filters) => request<Page<DropoutAlert>>("/advisor/alerts", filters),
    alertAction: (id: string, action: "acknowledge" | "resolve") => request<DropoutAlert>(`/advisor/alerts/${encodeURIComponent(id)}/${action}`, {}, "PATCH"),
  };
}

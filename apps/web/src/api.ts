import type * as T from "./types";
import type { StaffIdentity, StaffRole } from "./analytics";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<R>(path: string, init?: RequestInit): Promise<R> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as R;
  return (await res.json()) as R;
}

const get = <R>(path: string) => request<R>(path);
const post = <R>(path: string, body?: unknown) =>
  request<R>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const staffGet = <R>(role: StaffRole, path: string) =>
  request<R>(path, { headers: { "X-Staff-Role": role } });

export const api = {
  health: () => get<{ status: string; mode: string }>("/health"),
  overview: () => get<T.Overview>("/demo/overview"),
  staff: {
    current: (role: StaffRole, signal: AbortSignal) =>
      request<StaffIdentity>(`/auth/staff/${role}/session`, { signal }),
    login: (role: StaffRole, username: string, password: string) =>
      post<StaffIdentity>(`/auth/staff/${role}/session`, { username, password }),
    logout: (role: StaffRole) =>
      request<void>(`/auth/staff/${role}/session`, { method: "DELETE" }),
  },
  classroom: {
    current: () => get<T.ClassroomStudent>("/classroom/student/session"),
    login: (username: string, password: string) =>
      post<T.ClassroomStudent>("/classroom/student/session", { username, password }),
    logout: () => request<void>("/classroom/student/session", { method: "DELETE" }),
    lessons: () => get<T.ClassroomLesson[]>("/classroom/student/lessons"),
    study: (lesson: string, kind: "lesson_view" | "lesson_complete") =>
      post<void>(`/classroom/student/lessons/${encodeURIComponent(lesson)}/activity`,
        { kind, request_id: crypto.randomUUID() }),
  },

  simulate: {
    start: (rate_per_sec?: number) => post<{ running: boolean; rate_per_sec: number }>("/simulate/start", { rate_per_sec }),
    stop: () => post<{ running: boolean }>("/simulate/stop"),
    status: () => get<T.SimStatus>("/simulate/status"),
    telemetry: (input: T.TelemetryInput) => post<T.TelemetryResult>("/simulate/telemetry", input),
    burst: (count: number) => post<T.BurstResult>("/simulate/burst", { count }),
    lmsEvent: (input: T.LmsEventInput) => post<T.LmsEventResult>("/simulate/lms-event", input),
    cdc: (input: T.CdcInput) => post<T.CdcResult>("/simulate/cdc", input),
    scenario: (name: "at_risk_learner" | "broken_test_case" | "content_update" | "late_mobile_events") =>
      post<T.ScenarioResult>(`/simulate/scenario/${name}`),
  },

  pipeline: {
    stats: () => get<T.Stats>("/pipeline/stats"),
    topics: () => get<T.TopicSummary[]>("/pipeline/topics"),
    topic: (topic: string, limit = 20) =>
      get<T.TopicMessage[]>(`/pipeline/topics/${encodeURIComponent(topic)}?limit=${limit}`),
    dlq: (limit = 20) => get<T.DlqRecord[]>(`/pipeline/dlq?limit=${limit}`),
    silver: (limit = 50, learnerId?: string) =>
      get<T.LearningEvent[]>(`/pipeline/silver?limit=${limit}${learnerId ? `&learner_id=${encodeURIComponent(learnerId)}` : ""}`),
  },

  learner: {
    notifications: (id: string) => get<T.Notification[]>(`/learners/${id}/notifications`),
    recommendations: (id: string) => get<T.Recommendations>(`/learners/${id}/recommendations`),
    enroll: (learner_id: string, course_id: string) =>
      post<{ enrolled: string[] }>(`/learners/${learner_id}/enroll`, { course_id }),
    completeCourse: (learner_id: string, course_id: string) =>
      post<{ completed: string[] }>(`/learners/${learner_id}/complete-course`, { course_id }),
    submissions: (id: string) => get<T.Submission[]>(`/learners/${id}/submissions`),
    submit: (learner_id: string, assignment_id: string, code: string, request_id?: string) =>
      post<{ submission_id: string; status: string }>("/submissions", { learner_id, assignment_id, code, request_id }),
    submission: (id: string) => get<T.Submission>(`/submissions/${id}`),
  },

  instructor: {
    assessments: (courseId?: string) =>
      staffGet<T.AssessmentRow[]>("instructor", `/instructor/assessments${courseId ? `?course_id=${encodeURIComponent(courseId)}` : ""}`),
    heatmap: (contentId: string) => staffGet<T.Heatmap>("instructor", `/instructor/videos/${contentId}/heatmap`),
    engagement: (courseId: string) => staffGet<T.Engagement>("instructor", `/instructor/courses/${courseId}/engagement`),
    content: (contentId: string) => staffGet<T.ContentRecord>("instructor", `/instructor/content/${contentId}`),
    publish: (contentId: string, body: string, title?: string) =>
      request<T.PublishResult>(`/instructor/content/${contentId}`, {
        method: "POST", body: JSON.stringify({ body, title }), headers: { "X-Staff-Role": "instructor" },
      }),
  },

  advisor: {
    alerts: () => staffGet<T.RiskAlert[]>("advisor", "/advisor/demo-alerts"),
    risk: (learnerId: string) => staffGet<T.RiskDetail>("advisor", `/advisor/learners/${learnerId}/risk`),
  },

  admin: {
    progress: (orgId: string) => staffGet<T.OrgProgress>("admin", `/admin/organisations/${orgId}/progress`),
  },
};

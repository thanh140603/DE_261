import type * as T from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<R>(path: string, init?: RequestInit): Promise<R> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
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

export const api = {
  health: () => get<{ status: string; mode: string }>("/health"),
  overview: () => get<T.Overview>("/demo/overview"),

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
    submissions: (id: string) => get<T.Submission[]>(`/learners/${id}/submissions`),
    submit: (learner_id: string, assignment_id: string, code: string) =>
      post<{ submission_id: string; status: string }>("/submissions", { learner_id, assignment_id, code }),
    submission: (id: string) => get<T.Submission>(`/submissions/${id}`),
  },

  instructor: {
    assessments: (courseId?: string) =>
      get<T.AssessmentRow[]>(`/instructor/assessments${courseId ? `?course_id=${encodeURIComponent(courseId)}` : ""}`),
    heatmap: (contentId: string) => get<T.Heatmap>(`/instructor/videos/${contentId}/heatmap`),
    engagement: (courseId: string) => get<T.Engagement>(`/instructor/courses/${courseId}/engagement`),
    content: (contentId: string) => get<T.ContentRecord>(`/instructor/content/${contentId}`),
    publish: (contentId: string, body: string, title?: string) =>
      post<T.PublishResult>(`/instructor/content/${contentId}`, { body, title }),
  },

  advisor: {
    alerts: () => get<T.RiskAlert[]>("/advisor/demo-alerts"),
    risk: (learnerId: string) => get<T.RiskDetail>(`/advisor/learners/${learnerId}/risk`),
  },

  admin: {
    progress: (orgId: string) => get<T.OrgProgress>(`/admin/organisations/${orgId}/progress`),
  },
};

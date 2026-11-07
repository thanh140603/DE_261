import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { Icon } from "../../components/Icon";
import { Badge, Btn, Callout, Card, Chip, Meter, PageHead, Seg, SelectField, Status, useToast, type Tone } from "../../components/ui";
import { relTime, useAction, useFetch, type Fetched } from "../../hooks";
import { notificationIcon, notificationKind, useNotifications, type NotificationKind } from "../../notifications";
import { useStore } from "../../store";
import type { Course, LmsEventResult, Notification, Recommendations, Submission } from "../../types";

const SKILL_CODE: Record<string, string> = {
  sql: "SQL", python: "PY", data_engineering: "DE", machine_learning: "ML", analytics: "AN", cloud: "CL",
  ai: "AI", deep_learning: "DL", nlp: "NLP", computer_vision: "CV",
};
export const difficultyTone = (d?: string): Tone => (d === "easy" ? "good" : d === "medium" ? "warn" : d === "hard" ? "crit" : "neutral");
const cap = (s?: string) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const minutes = (c?: Course) => (c ? Math.round(c.lessons.reduce((a, l) => a + l.duration_sec, 0) / 60) : 0);
const CHANNEL_ICON: Record<string, string> = { in_app: "monitor", email: "mail", push: "phone", sms: "phone" };
const CHANNEL_LABEL: Record<string, string> = { in_app: "In-app", email: "Email", push: "Push", sms: "SMS" };

/** Deep links from notifications point at the old single-page learner view; map them to the new pages. */
export function deepLinkTarget(link: string | null): string | null {
  if (!link) return null;
  const submission = /submission=([\w-]+)/.exec(link)?.[1];
  if (submission) return `/learner/code-lab?submission=${submission}`;
  return link.startsWith("/") ? link : null;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function LearnerHome() {
  const { overview, learnerId, lastEventAt } = useStore();
  const learner = overview?.learners.find((l) => l.id === learnerId);
  const courseById = useMemo(() => new Map((overview?.courses ?? []).map((c) => [c.id, c])), [overview]);
  const recs = useFetch(learnerId ? () => api.learner.recommendations(learnerId) : null, [learnerId]);
  const subs = useFetch(learnerId ? () => api.learner.submissions(learnerId) : null, [learnerId]);
  useEffect(() => { if (learnerId) { void recs.reload(); void subs.reload(); } }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const notes = useNotifications(learnerId);
  const enrolled = enrolledOf(recs.data, learner?.course_ids ?? [], courseById);
  const inProgress = enrolled.filter((c) => !c.completed).length;
  const today = new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
  const navigate = useNavigate();

  return (
    <>
      <PageHead eyebrow={today} title={`${greeting()}, ${learner?.name.split(" ")[0] ?? "learner"}`}
        actions={<Btn icon="code" onClick={() => navigate("/learner/code-lab")}>Open code lab</Btn>}>
        {notes.unread} unread notification{notes.unread === 1 ? "" : "s"}
        {enrolled.length > 0 && <> · {inProgress} course{inProgress === 1 ? "" : "s"} in progress</>}
      </PageHead>
      <div className="grid-2-1">
        <div className="stack">
          <MyCourses learnerId={learnerId} recs={recs} courseById={courseById} />
          <Recommended learnerId={learnerId} recs={recs} courseById={courseById} />
          <RecentFeedback subs={subs} />
        </div>
        <div className="stack">
          <Notifications notes={notes} />
          <SimulateEvents />
        </div>
      </div>
    </>
  );
}

type Recs = Fetched<Recommendations>;

/** Older servers return no `enrolled` list; fall back to the learner's courses from the overview. */
function enrolledOf(recs: Recommendations | null, courseIds: string[], courseById: Map<string, Course>): Recommendations["enrolled"] {
  if (recs?.enrolled) return recs.enrolled;
  return courseIds.map((id) => ({ course_id: id, title: courseById.get(id)?.title ?? id, difficulty: "", category: "", completed: false }));
}

function MyCourses({ learnerId, recs, courseById }: { learnerId: string; recs: Recs; courseById: Map<string, Course> }) {
  const toast = useToast();
  const { overview } = useStore();
  const learner = overview?.learners.find((l) => l.id === learnerId);
  const complete = useAction(async (courseId: string, title: string) => {
    await api.learner.completeCourse(learnerId, courseId);
    await recs.reload();
    toast(`${title} marked as completed`);
  });
  const enrolled = enrolledOf(recs.data, learner?.course_ids ?? [], courseById);
  const done = enrolled.filter((c) => c.completed).length;
  return (
    <Card title="My courses" sub={enrolled.length ? `${enrolled.length} enrolled · ${done} completed` : undefined}>
      {complete.error && <Callout tone="bad">{complete.error}</Callout>}
      <Status loading={recs.loading && !recs.data} error={recs.error} empty={recs.data && enrolled.length === 0 ? "Not enrolled in any course yet. Pick one from the recommendations below." : false}>
        {enrolled.map((c) => {
          const course = courseById.get(c.course_id);
          return (
            <div className="course-row" key={c.course_id}>
              <div className={`course-ico${c.completed ? "" : " alt"}`}>{SKILL_CODE[course?.skill ?? ""] ?? c.title.slice(0, 2)}</div>
              <div style={{ minWidth: 0 }}>
                <div className="strong">{c.title}</div>
                <div className="muted small">{course ? `${course.lessons.length} lessons · ${minutes(course)} min` : ""}{c.category ? ` · ${cap(c.category)}` : ""}</div>
              </div>
              <div className="head-actions" style={{ alignItems: "center" }}>
                {c.difficulty && <Badge tone={difficultyTone(c.difficulty)} icon="chart">{cap(c.difficulty)}</Badge>}
                {c.completed
                  ? <Badge tone="good">Completed</Badge>
                  : <Btn size="sm" variant="ghost" onClick={() => void complete.run(c.course_id, c.title)} pending={complete.pending}>Mark complete</Btn>}
              </div>
            </div>
          );
        })}
      </Status>
    </Card>
  );
}

function Recommended({ learnerId, recs, courseById }: { learnerId: string; recs: Recs; courseById: Map<string, Course> }) {
  const toast = useToast();
  const enroll = useAction(async (courseId: string, title: string) => {
    await api.learner.enroll(learnerId, courseId);
    await recs.reload();
    toast(`Enrolled in ${title}`);
  });
  const next = recs.data?.next_step ?? null;
  const lessonStep = !!next && "lesson_id" in next && !!(next as { lesson_id?: string }).lesson_id; // older servers recommend a lesson
  const others = (recs.data?.courses ?? []).filter((c) => c.course_id !== next?.course_id);
  const nextCourse = next ? courseById.get(next.course_id) : undefined;
  return (
    <Card title="Recommended next" br="BR2" sub="Chosen by rules from your completed courses, course difficulty and track. Updated every time you finish a course.">
      {enroll.error && <Callout tone="bad">{enroll.error}</Callout>}
      <Status loading={recs.loading && !recs.data} error={recs.error} empty={recs.data && !next && others.length === 0 ? "You have explored every course in the catalogue." : false}>
        {next && (
          <div className="rec-hero">
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
              <div>
                <p className="eyebrow" style={{ color: "var(--brand-ink)" }}><Icon name="sparkle" />{lessonStep ? "Next lesson" : "Best next step"}</p>
                <h3 style={{ fontSize: 18, letterSpacing: "-.01em" }}>{next.title}</h3>
                <div className="chips" style={{ marginTop: 6 }}>
                  {next.difficulty && <Badge tone={difficultyTone(next.difficulty)} icon="chart">{cap(next.difficulty)}</Badge>}
                  {next.category && <Chip>{cap(next.category)}</Chip>}
                  {nextCourse && <Chip>{nextCourse.lessons.length} lessons · {minutes(nextCourse)} min</Chip>}
                </div>
              </div>
              {!lessonStep && <Btn variant="primary" onClick={() => void enroll.run(next.course_id, next.title)} pending={enroll.pending}>Enroll</Btn>}
            </div>
            <p className="rec-why"><Icon name="info" /><span><b>Why this course:</b> {next.reason}</span></p>
          </div>
        )}
        {others.length > 0 && (
          <div className="rec-list">
            {others.map((c) => {
              const locked = c.score === 0;
              return (
                <div className={`rec-card${locked ? " locked" : ""}`} key={c.course_id}>
                  <div>
                    <div className="strong">{c.title}</div>
                    <div className="chips" style={{ margin: "6px 0" }}>
                      {c.difficulty && <Badge tone={difficultyTone(c.difficulty)} icon="chart">{cap(c.difficulty)}</Badge>}
                      {c.category && <Chip>{cap(c.category)}</Chip>}
                    </div>
                    <p className="small muted">{c.reason}</p>
                  </div>
                  {locked
                    ? <Btn size="sm" disabled icon="lock">Locked</Btn>
                    : <Btn size="sm" onClick={() => void enroll.run(c.course_id, c.title)} pending={enroll.pending}>Enroll</Btn>}
                </div>
              );
            })}
          </div>
        )}
      </Status>
    </Card>
  );
}

function RecentFeedback({ subs }: { subs: Fetched<Submission[]> }) {
  const { overview } = useStore();
  const navigate = useNavigate();
  const title = (id: string) => overview?.assignments.find((a) => a.id === id)?.title ?? id;
  const latest = (subs.data ?? []).slice(0, 3);
  return (
    <Card title="Recent feedback" br="BR3" actions={<Btn size="sm" icon="code" onClick={() => navigate("/learner/code-lab")}>Code lab</Btn>}>
      <Status loading={subs.loading && !subs.data} error={subs.error} empty={subs.data && latest.length === 0 ? "No submissions yet. Open the code lab to submit your first solution." : false}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Assignment</th><th>Tests passed</th><th>Status</th><th className="r">Submitted</th></tr></thead>
            <tbody>
              {latest.map((s) => (
                <tr key={s.id}>
                  <td><button className="btn link" onClick={() => navigate(`/learner/code-lab?submission=${s.id}`)}>{title(s.assignment_id)}</button><span className="sub">Attempt {s.attempt_number}</span></td>
                  <td><Meter value={s.result?.pass_rate ?? null} /></td>
                  <td><SubmissionBadge status={s.status} passRate={s.result?.pass_rate} /></td>
                  <td className="r small muted nowrap">{relTime(s.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
    </Card>
  );
}

export function SubmissionBadge({ status, passRate }: { status: string; passRate?: number }) {
  if (status === "failed") return <Badge tone="crit">Error</Badge>;
  if (status !== "graded") return <Badge tone="info" icon="clock">{cap(status)}</Badge>;
  if (passRate === 1) return <Badge tone="good">All passed</Badge>;
  return <Badge tone="warn">Partly correct</Badge>;
}

const FILTERS: { value: "all" | NotificationKind; label: string }[] = [
  { value: "all", label: "All" }, { value: "deadline", label: "Deadlines" }, { value: "course", label: "Courses" }, { value: "feedback", label: "Feedback" },
];

function Notifications({ notes }: { notes: ReturnType<typeof useNotifications> }) {
  const [filter, setFilter] = useState<"all" | NotificationKind>("all");
  const navigate = useNavigate();
  const list = (notes.q.data ?? []).filter((n) => filter === "all" || notificationKind(n) === filter);
  return (
    <Card title="Notifications" br="BR1" sub={`${notes.unread} unread · delivered in real time`}
      actions={notes.unread > 0 ? <Btn size="sm" variant="ghost" onClick={notes.markSeen}>Mark all read</Btn> : undefined}>
      <Seg label="" ariaLabel="Filter notifications" value={filter} options={FILTERS} onChange={setFilter} />
      <Status loading={notes.q.loading && !notes.q.data} error={notes.q.error} empty={notes.q.data && list.length === 0 ? (filter === "all" ? "No notifications yet. Course updates, deadlines and feedback appear here as they happen." : "Nothing in this category.") : false}>
        <div style={{ marginTop: 6 }}>
          {list.map((n) => <NotificationItem key={n.id} n={n} unread={notes.isUnread(n)} onOpen={(to) => navigate(to)} />)}
        </div>
      </Status>
    </Card>
  );
}

function NotificationItem({ n, unread, onOpen }: { n: Notification; unread: boolean; onOpen: (to: string) => void }) {
  const target = deepLinkTarget(n.deep_link);
  return (
    <div className={`notif${unread ? " unread" : ""}${n.priority === "high" ? " high" : ""}`}>
      <div className="notif-ico"><Icon name={notificationIcon(n)} /></div>
      <div>
        <div className="notif-title">{n.title}{n.priority === "high" && <Badge tone="crit">High</Badge>}</div>
        <p className="notif-body">{n.body}</p>
        <div className="notif-meta">
          <span title={new Date(n.created_at).toLocaleString()}>{relTime(n.created_at)}</span>
          {n.channels.map((c) => <span className="ch" key={c}><Icon name={CHANNEL_ICON[c] ?? "bell"} />{CHANNEL_LABEL[c] ?? c}</span>)}
        </div>
        {target && <Btn size="sm" onClick={() => onOpen(target)}>Open <Icon name="arrow-right" /></Btn>}
      </div>
    </div>
  );
}

/** Demo controls: publish LMS events that the BR1 notification service routes to enrolled learners. */
function SimulateEvents() {
  const { overview, learnerId } = useStore();
  const courses = overview?.courses ?? [];
  const [courseId, setCourseId] = useState("");
  useEffect(() => { if (!courseId && courses.length) setCourseId(courses[0].id); }, [courses, courseId]);
  const [last, setLast] = useState<LmsEventResult | null>(null);
  const send = useAction(async (event_type: "assignment_created" | "deadline_approaching" | "course_updated") => {
    const assignment = overview?.assignments.find((a) => a.course_id === courseId);
    const r = await api.simulate.lmsEvent({
      event_type, course_id: courseId, assignment_id: assignment?.id,
      hours_to_deadline: event_type === "deadline_approaching" ? 12 : undefined,
      title: event_type === "assignment_created" ? "Week 3 practice set" : undefined,
    });
    setLast(r);
    return r;
  });
  const mine = last?.notifications.suppressed.filter((s) => s.learner_id === learnerId) ?? [];
  return (
    <details className="demo">
      <summary><Icon name="zap" />Demo controls · simulate course events</summary>
      <div className="filters" style={{ marginBottom: 10 }}>
        <SelectField label="Course" value={courseId} options={courses} onChange={setCourseId} render={(c) => c.title} valueOf={(c) => c.id} />
      </div>
      <div className="actions" style={{ marginTop: 0 }}>
        <Btn size="sm" onClick={() => void send.run("assignment_created")} pending={send.pending}>Create assignment</Btn>
        <Btn size="sm" onClick={() => void send.run("deadline_approaching")} pending={send.pending}>Send deadline reminder (12 h)</Btn>
        <Btn size="sm" onClick={() => void send.run("course_updated")} pending={send.pending}>Announce course update</Btn>
      </div>
      {send.error && <div className="mt"><Callout tone="bad">{send.error}</Callout></div>}
      {last && (
        <div className="mt">
          <Callout tone={mine.length ? "warn" : "good"}>
            {last.notifications.created} notification{last.notifications.created === 1 ? "" : "s"} created
            {last.notifications.suppressed.length > 0 && `, ${last.notifications.suppressed.length} suppressed`}
            {mine.length > 0 && <> · for this learner: {mine.map((s) => s.reason).join(", ")}</>}.
          </Callout>
        </div>
      )}
    </details>
  );
}

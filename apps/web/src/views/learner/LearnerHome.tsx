import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { ClassroomLessons } from "../../components/ClassroomStudent";
import { Icon } from "../../components/Icon";
import { Badge, Btn, Callout, Card, PageHead, Seg, SelectField, Status, useToast, type Tone } from "../../components/ui";
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
/** Course card colours (identity, not data): cool hues that sit with the sky-blue theme; all pass 4.5:1 with white text. */
const COURSE_COLOR: Record<string, string> = {
  sql: "#0277bd", python: "#00796b", data_engineering: "#3949ab", machine_learning: "#5e35b1", analytics: "#00838f",
  cloud: "#1565c0", ai: "#283593", deep_learning: "#37474f", nlp: "#00695c", computer_vision: "#4527a0",
};
const courseColor = (skill?: string) => COURSE_COLOR[skill ?? ""] ?? "#455a64";
/** "c-sql-101" -> "SQL-101": the short code LMS course cards show under the title. */
const courseCode = (id: string) => id.replace(/^c-/, "").toUpperCase();
const CHANNEL_ICON: Record<string, string> = { in_app: "monitor", email: "mail", push: "phone", sms: "phone" };
const CHANNEL_LABEL: Record<string, string> = { in_app: "In-app", email: "Email", push: "Push", sms: "SMS" };

/** Deep links from notifications point at the old single-page learner view; map them to the new pages. */
export function deepLinkTarget(link: string | null): string | null {
  if (!link) return null;
  const submission = /submission=([\w-]+)/.exec(link)?.[1];
  if (submission) return `/learner/code-lab?submission=${submission}`;
  return link.startsWith("/") ? link : null;
}

export function LearnerHome() {
  const { overview, learnerId, lastEventAt, student } = useStore();
  const learner = overview?.learners.find((l) => l.id === learnerId);
  const courseById = useMemo(() => new Map((overview?.courses ?? []).map((c) => [c.id, c])), [overview]);
  const recs = useFetch(learnerId ? () => api.learner.recommendations(learnerId) : null, [learnerId]);
  const subs = useFetch(learnerId ? () => api.learner.submissions(learnerId) : null, [learnerId]);
  useEffect(() => { if (learnerId) { void recs.reload(); void subs.reload(); } }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps
  const notes = useNotifications(learnerId);

  return (
    <>
      <PageHead title="Dashboard" br="BR1 · BR2" />
      <div className="dash">
      <div className="grid-2-1">
        <div className="stack">
          <MyCourses learnerId={learnerId} recs={recs} courseById={courseById} />
          {student && <ClassroomLessons courses={(overview?.courses ?? []).filter(
            (course) => enrolledOf(recs.data, learner?.course_ids ?? [], courseById).some(
              (item) => item.course_id === course.id && !item.completed,
            ),
          )} />}
          <Recommended learnerId={learnerId} recs={recs} courseById={courseById} />
        </div>
        <aside className="stack" aria-label={`Sidebar for ${learner?.name ?? "learner"}`}>
          <Notifications notes={notes} />
          <RecentFeedback subs={subs} />
          <SimulateEvents />
        </aside>
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
    <section aria-labelledby="my-courses">
      <div className="section-head">
        <h2 id="my-courses">My courses</h2>
        {enrolled.length > 0 && <span className="small muted">{enrolled.length} enrolled · {done} completed</span>}
      </div>
      {complete.error && <Callout tone="bad">{complete.error}</Callout>}
      <Status loading={recs.loading && !recs.data} error={recs.error} empty={recs.data && enrolled.length === 0 ? "You are not enrolled in any course yet. Pick one from Recommended courses below." : false}>
        <div className="course-cards">
          {enrolled.map((c) => {
            const course = courseById.get(c.course_id);
            return (
              <article className="ccard" key={c.course_id} style={{ ["--cc" as string]: courseColor(course?.skill) }}>
                <div className="ccard-band"><span>{SKILL_CODE[course?.skill ?? ""] ?? c.title.slice(0, 2)}</span></div>
                <div className="ccard-body">
                  <h3 className="ccard-title">{c.title}</h3>
                  <p className="ccard-code">{courseCode(c.course_id)}{c.category ? ` · ${cap(c.category)}` : ""}</p>
                  {course && <p className="ccard-meta">{course.lessons.length} lessons · {minutes(course)} min{c.difficulty ? ` · ${cap(c.difficulty)}` : ""}</p>}
                </div>
                <div className="ccard-foot">
                  {c.completed
                    ? <span className="done"><Icon name="check" />Completed</span>
                    : <><span className="small muted">In progress</span><Btn size="sm" variant="link" onClick={() => void complete.run(c.course_id, c.title)} pending={complete.pending}>Mark complete</Btn></>}
                </div>
              </article>
            );
          })}
        </div>
      </Status>
    </section>
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
  const cards = [...(next ? [{ ...next, top: true }] : []), ...others.map((c) => ({ ...c, top: false }))];
  return (
    <section aria-labelledby="recommended">
      <div className="section-head">
        <h2 id="recommended">Recommended courses <span className="br">BR2</span></h2>
        <span className="small muted">Based on the courses you have finished, their difficulty and track</span>
      </div>
      {enroll.error && <Callout tone="bad">{enroll.error}</Callout>}
      <Status loading={recs.loading && !recs.data} error={recs.error} empty={recs.data && cards.length === 0 ? "You have explored every course in the catalogue." : false}>
        <div className="course-cards">
          {cards.map((c) => {
            const course = courseById.get(c.course_id);
            const locked = !c.top && c.score === 0;
            return (
              <article className={`ccard${locked ? " locked" : ""}${c.top ? " top" : ""}`} key={c.course_id} style={{ ["--cc" as string]: courseColor(course?.skill) }}>
                <div className="ccard-band">
                  <span>{SKILL_CODE[course?.skill ?? ""] ?? c.title.slice(0, 2)}</span>
                  {c.top && <em className="ccard-flag">{lessonStep ? "Next lesson" : "Recommended for you"}</em>}
                </div>
                <div className="ccard-body">
                  <h3 className="ccard-title">{c.title}</h3>
                  <p className="ccard-code">{courseCode(c.course_id)}{c.category ? ` · ${cap(c.category)}` : ""}</p>
                  <p className="ccard-meta">{course ? `${course.lessons.length} lessons · ${minutes(course)} min` : ""}{c.difficulty ? `${course ? " · " : ""}${cap(c.difficulty)}` : ""}</p>
                  <p className="ccard-why">{c.top && <b>Why: </b>}{c.reason}</p>
                </div>
                <div className="ccard-foot">
                  {locked
                    ? <span className="small muted"><Icon name="lock" /> Not available yet</span>
                    : lessonStep && c.top ? <span className="small muted">Continue in your course</span>
                      : <Btn size="sm" variant={c.top ? "primary" : undefined} onClick={() => void enroll.run(c.course_id, c.title)} pending={enroll.pending}>Enroll</Btn>}
                </div>
              </article>
            );
          })}
        </div>
      </Status>
    </section>
  );
}

function RecentFeedback({ subs }: { subs: Fetched<Submission[]> }) {
  const { overview } = useStore();
  const navigate = useNavigate();
  const title = (id: string) => overview?.assignments.find((a) => a.id === id)?.title ?? id;
  const latest = (subs.data ?? []).slice(0, 4);
  return (
    <Card title="Recent feedback" br="BR3" className="block">
      <Status loading={subs.loading && !subs.data} error={subs.error} empty={subs.data && latest.length === 0 ? "No submissions yet. Open Assignments to submit your first solution." : false}>
        <ul className="feed">
          {latest.map((s) => {
            const tests = s.result?.tests ?? [];
            const passed = tests.filter((t) => t.status === "passed").length;
            return (
              <li key={s.id}>
                <button className="btn link" onClick={() => navigate(`/learner/code-lab?submission=${s.id}`)}>{title(s.assignment_id)}</button>
                <div className="feed-meta">
                  {tests.length > 0 && <span className="strong num">{passed}/{tests.length} tests</span>}
                  <SubmissionBadge status={s.status} passRate={s.result?.pass_rate} />
                </div>
                <span className="xs muted">Attempt {s.attempt_number} · {relTime(s.submitted_at)}</span>
              </li>
            );
          })}
        </ul>
      </Status>
      <div className="block-foot"><Btn size="sm" variant="link" onClick={() => navigate("/learner/code-lab")}>View all assignments</Btn></div>
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
    <Card title={<>Notifications{notes.unread > 0 && <span className="count-pill">{notes.unread}</span>}</>} br="BR1" className="block"
      actions={notes.unread > 0 ? <Btn size="sm" variant="link" onClick={notes.markSeen}>Mark all as read</Btn> : undefined}>
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
        {target && <Btn size="sm" variant="link" onClick={() => onOpen(target)}>Open</Btn>}
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
      <summary><Icon name="zap" />Demo controls: simulate course events</summary>
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

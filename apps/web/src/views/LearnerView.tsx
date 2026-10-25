import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatTime, pct, useAction, useFetch } from "../hooks";
import { Btn, Panel, Select, Status, Tag, ViewHead } from "../components/ui";
import type { LmsEventResult, Submission, TestResult } from "../types";

export function LearnerView() {
  const { overview, lastEventAt } = useStore();
  const learners = overview?.learners ?? [];
  const courses = overview?.courses ?? [];
  const [learnerId, setLearnerId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [sentTick, setSentTick] = useState(0);
  useEffect(() => {
    if (!learnerId && learners.length) setLearnerId(learners[0].id);
  }, [learners, learnerId]);
  useEffect(() => {
    if (!courseId && courses.length) setCourseId(courses[0].id);
  }, [courses, courseId]);
  const learner = learners.find((l) => l.id === learnerId) ?? null;

  const [last, setLast] = useState<LmsEventResult | null>(null);
  const send = useAction(async (event_type: "assignment_created" | "deadline_approaching" | "course_updated") => {
    if (!courseId) throw new Error("Choose a course to notify about");
    const assignment = overview?.assignments.find((a) => a.course_id === courseId);
    const r = await api.simulate.lmsEvent({
      event_type,
      course_id: courseId,
      assignment_id: assignment?.id,
      hours_to_deadline: event_type === "deadline_approaching" ? 12 : undefined,
      title: event_type === "assignment_created" ? "Week 3 practice set" : undefined,
    });
    setLast(r);
    setSentTick((t) => t + 1);
    return r;
  });
  const mine = last?.notifications.suppressed.filter((s) => s.learner_id === learnerId) ?? [];

  return (
    <>
      <ViewHead title="Learner">
        Learners get a notification when something important changes in a course, a next step recommended from
        their live session and long-term features, and detailed feedback when they submit code.
      </ViewHead>
      <div className="toolbar">
        <Select label="Course" value={courseId} options={courses} onChange={setCourseId} render={(c) => c.title} />
        <Btn onClick={() => void send.run("assignment_created")} pending={send.pending}>Create assignment</Btn>
        <Btn onClick={() => void send.run("deadline_approaching")} pending={send.pending}>Send deadline reminder (12 h)</Btn>
        <Btn onClick={() => void send.run("course_updated")} pending={send.pending}>Announce course update</Btn>
      </div>
      {send.error && <div className="error">{send.error}</div>}
      {last && (
        <div className={mine.length ? "notice" : "ok"}>
          Event routed: {last.notifications.created} notification{last.notifications.created === 1 ? "" : "s"} created
          {last.notifications.suppressed.length > 0 && `, ${last.notifications.suppressed.length} suppressed`}
          {mine.length > 0 && <> — this learner: {mine.map((s) => s.reason).join(", ")}</>}.
        </div>
      )}
      <div className="toolbar">
        <Select label="Learner" value={learnerId} options={learners} onChange={setLearnerId} render={(l) => `${l.name} (${l.id})`} />
        {learner && <span className="muted">Enrolled in {learner.course_ids.length} course{learner.course_ids.length === 1 ? "" : "s"}</span>}
      </div>
      {learner && (
        <div className="grid">
          <Notifications learnerId={learner.id} tick={lastEventAt} sentTick={sentTick} />
          <NextStep learnerId={learner.id} tick={lastEventAt} />
          <div style={{ gridColumn: "1 / -1" }}>
            <CodeFeedback learnerId={learner.id} />
          </div>
        </div>
      )}
    </>
  );
}

function Notifications({ learnerId, tick, sentTick }: { learnerId: string; tick: number; sentTick: number }) {
  const q = useFetch(() => api.learner.notifications(learnerId), [learnerId]);
  useEffect(() => { void q.reload(); }, [tick, sentTick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel title="Notifications" br="BR1">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "No notifications yet. Use the buttons above to create an assignment or send a reminder." : false}>
        <div className="list">
          {q.data?.map((n) => (
            <div className={`item${n.priority === "high" ? " high" : ""}`} key={n.id}>
              <div><strong>{n.title}</strong></div>
              <div>{n.body}</div>
              <div className="meta">
                <span className="num">{formatTime(n.created_at)}</span>
                <span>{n.channels.join(", ")}</span>
                <span>{n.priority} priority</span>
                <span>{n.source_event_type}</span>
              </div>
            </div>
          ))}
        </div>
      </Status>
    </Panel>
  );
}

function NextStep({ learnerId, tick }: { learnerId: string; tick: number }) {
  const q = useFetch(() => api.learner.recommendations(learnerId), [learnerId]);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const complete = useAction(async (course_id: string) => {
    await api.learner.completeCourse(learnerId, course_id);
    await q.reload();
  });
  const enroll = useAction(async (course_id: string) => {
    await api.learner.enroll(learnerId, course_id);
    await q.reload();
  });
  const nextStep = q.data?.next_step ?? null;
  const diffKind = (d: string): "ok" | "warn" | "bad" =>
    d === "easy" ? "ok" : d === "medium" ? "warn" : "bad";
  return (
    <Panel title="Courses" br="BR2">
      {complete.error && <div className="error">{complete.error}</div>}
      {enroll.error && <div className="error">{enroll.error}</div>}
      <Status loading={q.loading && !q.data} error={q.error}>
        <h3>Enrolled</h3>
        <div className="list">
          {q.data?.enrolled.map((c) => (
            <div className="item" key={c.course_id}>
              <div>
                <strong>{c.title}</strong> <Tag kind={diffKind(c.difficulty)}>{c.difficulty}</Tag>
                <span className="muted"> {c.category}</span>
              </div>
              {c.completed ? (
                <Tag kind="ok">Completed</Tag>
              ) : (
                <Btn onClick={() => void complete.run(c.course_id)} pending={complete.pending}>Complete course</Btn>
              )}
            </div>
          ))}
        </div>

        <h3 style={{ marginTop: 12 }}>Which course to enroll next</h3>
        {nextStep && (
          <div className="item" style={{ borderLeft: "3px solid var(--green)", marginBottom: 8 }}>
            <div>
              <strong>Recommended: {nextStep.title}</strong>{" "}
              <Tag kind={diffKind(nextStep.difficulty)}>{nextStep.difficulty}</Tag>
              <span className="muted"> {nextStep.category}</span>
            </div>
            <div className="muted small">{nextStep.reason}</div>
            <div className="actions" style={{ marginTop: 8 }}>
              <Btn primary onClick={() => void enroll.run(nextStep.course_id)} pending={enroll.pending}>Enroll</Btn>
            </div>
          </div>
        )}
        <div className="list">
          {q.data?.courses
            .filter((c) => c.course_id !== nextStep?.course_id)
            .map((c) => (
              <div className="item" key={c.course_id}>
                <div>
                  <strong>{c.title}</strong> <Tag kind={diffKind(c.difficulty)}>{c.difficulty}</Tag>
                  <span className="muted"> {c.category}</span>
                </div>
                <div className="muted small">{c.reason}</div>
                <Btn onClick={() => void enroll.run(c.course_id)} pending={enroll.pending}>Enroll</Btn>
              </div>
            ))}
        </div>
      </Status>
    </Panel>
  );
}

function TestRows({ tests }: { tests: TestResult[] }) {
  return (
    <table>
      <thead><tr><th>Test</th><th>Status</th><th className="num">ms</th><th>Detail</th></tr></thead>
      <tbody>
        {tests.map((t) => (
          <tr key={t.test_case_id}>
            <td>{t.test_case_id}</td>
            <td><Tag kind={t.status === "passed" ? "ok" : t.status === "failed" ? "warn" : "bad"}>{t.status}</Tag></td>
            <td className="num">{t.duration_ms}</td>
            <td>{t.diff ? <pre className="block">{t.diff}</pre> : t.status === "passed" ? "" : <span className="muted small">expected {t.expected ?? "–"}, got {t.actual ?? "–"}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CodeFeedback({ learnerId }: { learnerId: string }) {
  const { overview } = useStore();
  const assignments = overview?.assignments ?? [];
  const [assignmentId, setAssignmentId] = useState("");
  useEffect(() => { if (!assignmentId && assignments.length) setAssignmentId(assignments[0].id); }, [assignments, assignmentId]);
  const assignment = assignments.find((a) => a.id === assignmentId);
  const [code, setCode] = useState("");
  useEffect(() => { setCode(assignment?.starter_code ?? ""); }, [assignment?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const history = useFetch(() => api.learner.submissions(learnerId), [learnerId]);
  const [current, setCurrent] = useState<Submission | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const submit = useAction(async () => {
    const r = await api.learner.submit(learnerId, assignmentId, code);
    setPollError(null);
    setCurrent({ id: r.submission_id, learner_id: learnerId, assignment_id: assignmentId, language: assignment?.language ?? "", status: "queued", attempt_number: 0, submitted_at: new Date().toISOString(), result: null, feedback: null });
    return r;
  });

  useEffect(() => {
    if (!current || current.status === "graded" || current.status === "failed") return;
    timer.current = window.setTimeout(async () => {
      try {
        const s = await api.learner.submission(current.id);
        setCurrent(s);
        if (s.status === "graded" || s.status === "failed") void history.reload();
      } catch (e) {
        setPollError((e as Error).message);
      }
    }, 700);
    return () => window.clearTimeout(timer.current);
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel title="Code feedback" br="BR3">
      <div className="toolbar" style={{ margin: "0 0 10px" }}>
        <Select label="Assignment" value={assignmentId} options={assignments} onChange={setAssignmentId} render={(a) => `${a.title} (${a.language})`} />
        {assignment && <span className="muted" style={{ maxWidth: "60ch" }}>{assignment.prompt}</span>}
      </div>
      <textarea className="code" rows={10} value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} aria-label="Code" />
      <div className="actions" style={{ marginTop: 8 }}>
        <Btn primary onClick={() => void submit.run()} pending={submit.pending} disabled={!assignmentId || !code.trim()}>Submit code</Btn>
        {current && current.status !== "graded" && current.status !== "failed" && <span className="muted">Queued for the sandbox, status: {current.status}…</span>}
      </div>
      {submit.error && <div className="error">{submit.error}</div>}
      {pollError && <div className="error">{pollError}</div>}
      {current?.result && (
        <div style={{ marginTop: 8 }}>
          <div className={current.status === "failed" ? "error" : current.result.pass_rate === 1 ? "ok" : "notice"}>
            {current.feedback?.summary ?? `Status: ${current.status}`} — pass rate {pct(current.result.pass_rate)}, {current.result.runtime_ms} ms, {current.result.memory_kb} kB
          </div>
          {current.feedback && current.feedback.hints.length > 0 && (
            <ul>{current.feedback.hints.map((h, i) => <li key={i}>{h}</li>)}</ul>
          )}
          <TestRows tests={current.result.tests} />
          {current.feedback?.stderr_excerpt && (
            <details style={{ marginTop: 8 }}>
              <summary>stderr</summary>
              <pre className="block">{current.feedback.stderr_excerpt}</pre>
            </details>
          )}
        </div>
      )}
      <h3 style={{ marginTop: 16 }}>Previous submissions</h3>
      <Status loading={history.loading && !history.data} error={history.error} empty={history.data && history.data.length === 0 ? "Submit code to see feedback here." : false}>
        <table>
          <thead><tr><th>When</th><th>Assignment</th><th className="num">Attempt</th><th>Status</th><th className="num">Pass rate</th><th>Summary</th></tr></thead>
          <tbody>
            {history.data?.map((s) => (
              <tr key={s.id}>
                <td className="num">{formatTime(s.submitted_at)}</td>
                <td>{assignments.find((a) => a.id === s.assignment_id)?.title ?? s.assignment_id}</td>
                <td className="num">{s.attempt_number}</td>
                <td><Tag kind={s.status === "graded" ? "ok" : s.status === "failed" ? "bad" : "blue"}>{s.status}</Tag></td>
                <td className="num">{s.result ? pct(s.result.pass_rate) : "–"}</td>
                <td className="muted">{s.feedback?.summary ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Status>
    </Panel>
  );
}

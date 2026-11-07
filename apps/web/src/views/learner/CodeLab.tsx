import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { Icon } from "../../components/Icon";
import { Badge, Btn, Callout, Card, Chip, Meter, PageHead, SelectField, Status } from "../../components/ui";
import { relTime, useAction, useFetch, usePersisted } from "../../hooks";
import { useStore } from "../../store";
import type { Submission, TestResult } from "../../types";
import { SubmissionBadge } from "./LearnerHome";

const ACTIVE = new Set(["queued", "running"]);

export function CodeLab() {
  const { overview, learnerId } = useStore();
  const assignments = overview?.assignments ?? [];
  const [params, setParams] = useSearchParams();
  const linked = params.get("submission");
  const [assignmentId, setAssignmentId] = usePersisted("lab-assignment", "");
  const assignment = assignments.find((a) => a.id === assignmentId);
  useEffect(() => { if (!assignment && assignments.length) setAssignmentId(assignments[0].id); }, [assignment, assignments, setAssignmentId]);

  const history = useFetch(learnerId ? () => api.learner.submissions(learnerId) : null, [learnerId]);
  const [current, setCurrent] = useState<Submission | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);

  // a notification deep link opens one submission (and its assignment)
  useEffect(() => {
    if (!linked) return;
    api.learner.submission(linked).then((s) => { setAssignmentId(s.assignment_id); setCurrent(s); }).catch((e: Error) => setPollError(e.message));
  }, [linked, setAssignmentId]);

  const attempts = useMemo(() => (history.data ?? []).filter((s) => s.assignment_id === assignmentId), [history.data, assignmentId]);
  const shown = current && current.assignment_id === assignmentId ? current : attempts[0] ?? null;

  const [code, setCode] = useState("");
  useEffect(() => { setCode(assignment?.starter_code ?? ""); }, [assignment?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = useAction(async () => {
    const r = await api.learner.submit(learnerId, assignmentId, code);
    setPollError(null);
    setParams({}, { replace: true });
    setCurrent({ id: r.submission_id, learner_id: learnerId, assignment_id: assignmentId, language: assignment?.language ?? "", status: "queued", attempt_number: attempts.length + 1, submitted_at: new Date().toISOString(), result: null, feedback: null });
    return r;
  });
  useEffect(() => {
    if (!current || !ACTIVE.has(current.status)) return;
    const t = window.setTimeout(async () => {
      try {
        const s = await api.learner.submission(current.id);
        setCurrent(s);
        if (!ACTIVE.has(s.status)) void history.reload();
      } catch (e) { setPollError((e as Error).message); }
    }, 700);
    return () => window.clearTimeout(t);
  }, [current]); // eslint-disable-line react-hooks/exhaustive-deps

  const course = overview?.courses.find((c) => c.id === assignment?.course_id);
  const grading = current && ACTIVE.has(current.status);
  return (
    <>
      <PageHead eyebrow={<>{course?.title ?? "Assignments"} <Icon name="arrow-right" /> Assignments</>} title={assignment?.title ?? "Code lab"}
        actions={<SelectField label="Assignment" value={assignmentId} options={assignments} onChange={(v) => { setAssignmentId(v); setCurrent(null); setParams({}, { replace: true }); }} render={(a) => `${a.title} (${a.language})`} valueOf={(a) => a.id} />}>
        {assignment && <span className="chips" style={{ marginTop: 2 }}>
          <Chip>{assignment.language === "sql" ? "SQL" : "Python"}</Chip>
          <Chip>{assignment.test_case_ids.length} tests</Chip>
          <Chip>{attempts.length} attempt{attempts.length === 1 ? "" : "s"}</Chip>
        </span>}
      </PageHead>

      <div className="grid-1-1">
        <Card title="Task">
          <p>{assignment?.prompt}</p>
          <div className="mt">
            <Editor value={code} onChange={setCode} language={assignment?.language ?? "python"} />
          </div>
          <div className="actions">
            <Btn variant="primary" icon="upload" onClick={() => void submit.run()} pending={submit.pending} disabled={!assignmentId || !code.trim() || !!grading}>Submit code</Btn>
            <Btn variant="ghost" onClick={() => setCode(assignment?.starter_code ?? "")}>Reset to starter code</Btn>
            {grading && <span className="grading" aria-live="polite"><span className="spinner" />{current!.status === "queued" ? "Queued for the sandbox" : "Running tests in the sandbox"}…</span>}
          </div>
          {submit.error && <div className="mt"><Callout tone="bad">{submit.error}</Callout></div>}
          {pollError && <div className="mt"><Callout tone="bad">{pollError}</Callout></div>}
        </Card>
        <Feedback submission={shown} />
      </div>

      <Card className="mt" title="Previous attempts" sub="Every submission is graded in an isolated sandbox and kept here.">
        <Status loading={history.loading && !history.data} error={history.error} empty={history.data && attempts.length === 0 ? "No attempts for this assignment yet." : false}>
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Attempt</th><th>Submitted</th><th>Status</th><th>Tests passed</th><th>Summary</th></tr></thead>
              <tbody>
                {attempts.map((s) => (
                  <tr key={s.id} className="selectable" aria-selected={shown?.id === s.id} onClick={() => setCurrent(s)} style={{ cursor: "pointer" }}>
                    <td className="num strong">{s.attempt_number}</td>
                    <td className="num nowrap">{relTime(s.submitted_at)}</td>
                    <td><SubmissionBadge status={s.status} passRate={s.result?.pass_rate} /></td>
                    <td><Meter value={s.result?.pass_rate ?? null} /></td>
                    <td className="muted">{s.feedback?.summary ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Status>
      </Card>
    </>
  );
}

function Editor({ value, onChange, language }: { value: string; onChange: (v: string) => void; language: string }) {
  const gutter = useRef<HTMLDivElement>(null);
  const escaped = useRef(false);
  const lines = Math.max(1, value.split("\n").length);
  function keyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Escape") { escaped.current = true; return; }
    if (e.key === "Tab" && !e.shiftKey && !escaped.current) {
      e.preventDefault();
      const el = e.currentTarget, start = el.selectionStart, end = el.selectionEnd;
      onChange(`${value.slice(0, start)}    ${value.slice(end)}`);
      requestAnimationFrame(() => { el.selectionStart = el.selectionEnd = start + 4; });
    }
    escaped.current = false;
  }
  return (
    <div className="editor">
      <div className="editor-bar">
        <span className="editor-tab"><Icon name="file" />{language === "sql" ? "solution.sql" : "solution.py"}</span>
        <span>Tab indents · Esc then Tab leaves the editor</span>
      </div>
      <div className="editor-body">
        <div className="editor-gutter" ref={gutter} aria-hidden="true">{Array.from({ length: lines }, (_, i) => i + 1).join("\n")}</div>
        <textarea className="editor-text" aria-label="Code" spellCheck={false} value={value} rows={Math.max(10, lines + 1)}
          onChange={(e) => onChange(e.target.value)} onKeyDown={keyDown}
          onScroll={(e) => { if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop; }} />
      </div>
    </div>
  );
}

function Feedback({ submission: s }: { submission: Submission | null }) {
  const tests = s?.result?.tests ?? [];
  const passed = tests.filter((t) => t.status === "passed").length;
  return (
    <Card title="Feedback" br="BR3" sub={s ? `Attempt ${s.attempt_number} · submitted ${relTime(s.submitted_at)}` : undefined} label="Feedback">
      {!s && <p className="empty">Submit your solution to get test-by-test feedback, hints and runtime details.</p>}
      {s && !s.result && <div className="loading"><span className="spinner" />Waiting for the sandbox result…</div>}
      {s?.result && (
        <>
          <div className="result-head">
            <div className="result-score">{passed}<small> / {tests.length} tests passed</small></div>
            {s.status === "failed" ? <Badge tone="crit">Could not run</Badge> : passed === tests.length ? <Badge tone="good">All passed</Badge> : <Badge tone="warn">Partly correct</Badge>}
          </div>
          {tests.length > 0 && (
            <div className="segbar" style={{ marginTop: 12, maxWidth: 420 }} role="img" aria-label={`${passed} passed, ${tests.length - passed} failed`}>
              {passed > 0 && <i style={{ flex: passed, background: "var(--good)" }} />}
              {tests.length - passed > 0 && <i style={{ flex: tests.length - passed, background: "var(--critical)" }} />}
            </div>
          )}
          <div className="kv">
            <div><span>Runtime</span><b className="num">{s.result.runtime_ms} ms</b></div>
            <div><span>Memory</span><b className="num">{(s.result.memory_kb / 1024).toFixed(1)} MB</b></div>
            <div><span>Exit code</span><b className="num">{s.result.exit_code}</b></div>
          </div>
          {s.feedback && (
            <div className="mt" style={{ display: "grid", gap: 8 }}>
              <Callout tone={passed === tests.length ? "good" : "warn"} icon="sparkle">
                <b>{s.feedback.summary}</b>
                {s.feedback.hints.length > 0 && <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{s.feedback.hints.map((h, i) => <li key={i}>{h}</li>)}</ul>}
              </Callout>
            </div>
          )}
          <div className="table-wrap mt">
            <table className="t">
              <thead><tr><th /><th>Test</th><th>Result</th><th className="r">Time</th></tr></thead>
              <tbody>{tests.map((t) => <TestRow key={t.test_case_id} t={t} />)}</tbody>
            </table>
          </div>
          <details className="data-table">
            <summary>Program output (stderr)</summary>
            {s.feedback?.stderr_excerpt || s.result.stderr ? <pre className="block">{s.feedback?.stderr_excerpt ?? s.result.stderr}</pre> : <p className="muted small" style={{ marginTop: 6 }}>Nothing was written to stderr.</p>}
          </details>
        </>
      )}
    </Card>
  );
}

function TestRow({ t }: { t: TestResult }) {
  const ok = t.status === "passed";
  return (
    <tr>
      <td><span className={`status-ico ${ok ? "pass" : t.status === "failed" ? "fail" : "warn"}`} title={t.status}><Icon name={ok ? "check" : t.status === "failed" ? "x" : "alert"} /></span></td>
      <td><span className="mono strong">{t.test_case_id}</span></td>
      <td>
        {ok ? <span className="small">Passed</span>
          : t.diff ? <pre className="block" style={{ marginTop: 0 }}>{t.diff}</pre>
            : <div className="diff"><span className="exp">expected {t.expected ?? "–"}</span><span className="act">got {t.actual ?? (t.status === "timeout" ? "timeout" : "error")}</span></div>}
      </td>
      <td className="r num nowrap">{t.duration_ms} ms</td>
    </tr>
  );
}

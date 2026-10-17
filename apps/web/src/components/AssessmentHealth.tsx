import { useState } from "react";
import { analyticsApi, type AssessmentStat } from "../analytics";
import { pct, useFetch } from "../hooks";
import { AnalyticsAccess, localDateTime, Pager, useAnalyticsPolling, utcDay } from "./AnalyticsAccess";
import { Btn, Panel, Select, Status, Tag } from "./ui";

export function AssessmentHealth() {
  return <Panel title="Assessment health" br="BR4"><AnalyticsAccess role="instructor">
    {(token, session) => <AssessmentResults token={token} courses={session.courses} />}
  </AnalyticsAccess></Panel>;
}

function AssessmentResults({ token, courses }: { token: string; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useState(courses.find((c) => c.id === "c-py-201")?.id ?? courses[0]?.id ?? "");
  const [assignment, setAssignment] = useState("");
  const [state, setState] = useState("");
  const [severity, setSeverity] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<AssessmentStat | null>(null);
  const filters = { assignment_id: assignment, status: state, severity, start: utcDay(start), end: utcDay(end, true), offset, limit: 20 };
  const q = useFetch(course ? () => analyticsApi(token).questions(course, filters) : null, [token, course, assignment, state, severity, start, end, offset]);
  useAnalyticsPolling(q.reload);
  const cases = useFetch(selected ? () => analyticsApi(token).cases(selected.question_id, { version: selected.question_version, start: q.data?.window_start, end: q.data?.window_end, limit: 100 }) : null, [token, selected, q.data?.window_start, q.data?.window_end]);
  useAnalyticsPolling(cases.reload);
  function change(setter: (value: string) => void, value: string) { setter(value); setOffset(0); setSelected(null); }
  return <>
    <p className="muted small">Low pass rates identify assessments for instructor review. They do not establish a grading defect.</p>
    <div className="toolbar">
      <Select label="Assessment course" value={course} options={courses} onChange={(v) => change(setCourse, v)} render={(c) => c.title} />
      <label className="field"><span>Assignment ID</span><input value={assignment} onChange={(e) => change(setAssignment, e.target.value)} placeholder="All assignments" /></label>
      <label className="field"><span>Assessment status</span><select value={state} onChange={(e) => change(setState, e.target.value)}>
        <option value="">All states</option>{["NORMAL", "INSUFFICIENT_DATA", "LOW_PASS_RATE", "SUSPICIOUS_TEST_CASE", "NEEDS_REVIEW"].map((s) => <option key={s}>{s}</option>)}
      </select></label>
      <label className="field"><span>Assessment severity</span><select value={severity} onChange={(e) => change(setSeverity, e.target.value)}><option value="">All severities</option>{["INFO", "MEDIUM", "HIGH"].map((s) => <option key={s}>{s}</option>)}</select></label>
      <label className="field"><span>From (UTC)</span><input type="date" value={start} onChange={(e) => change(setStart, e.target.value)} /></label>
      <label className="field"><span>Through (UTC)</span><input type="date" value={end} onChange={(e) => change(setEnd, e.target.value)} /></label>
      <Btn onClick={() => void q.reload()}>Refresh assessments</Btn>
    </div>
    <Status loading={q.loading} error={q.error} empty={q.data?.total === 0 ? "No evaluated questions match. Load the synthetic fixture or adjust your filters." : false}>
      <p className="muted small">{q.data?.total} question versions · {localDateTime(q.data?.window_start)} to {localDateTime(q.data?.window_end)}. Updates refresh every 5 seconds.</p>
      <div className="analytics-table"><table><caption className="sr-only">Question pass rates and review reasons</caption>
        <thead><tr><th>Question / version</th><th>Valid / students</th><th>Pass rate</th><th>First / latest</th><th>Invalid / infrastructure</th><th>Review</th></tr></thead>
        <tbody>{q.data?.items.map((r) => <tr key={r.id} className={r.state === "LOW_PASS_RATE" || r.state === "NEEDS_REVIEW" ? "anomalous" : undefined}>
          <td><button className="btn" onClick={() => setSelected(r)} aria-pressed={selected?.id === r.id}>{r.question_title ?? r.question_id} · v{r.question_version}</button><div className="muted small">{r.assignment_title}</div></td>
          <td className="num">{r.total_valid_evaluations} / {r.unique_students}</td><td className="num">{pct(r.pass_rate)}</td>
          <td className="num">{pct(r.first_attempt_pass_rate)} / {pct(r.latest_attempt_pass_rate)}</td>
          <td className="num">{r.invalid_evaluations} / {r.infrastructure_errors}</td><td><Review row={r} /></td>
        </tr>)}</tbody>
      </table></div>
      <Pager offset={offset} total={q.data?.total ?? 0} onChange={setOffset} />
    </Status>
    {selected && <section className="analytics-detail" aria-label="Selected question test cases">
      <h3>Test cases · {selected.question_title ?? selected.question_id} · v{selected.question_version}</h3>
      <Status loading={cases.loading} error={cases.error} empty={cases.data?.total === 0 ? "No required test-case evaluations in this window." : false}>
        <div className="analytics-table"><table><thead><tr><th>Test / version</th><th>Passed / valid</th><th>Pass rate</th><th>Students</th><th>Review reason</th></tr></thead>
          <tbody>{cases.data?.items.map((r) => <tr key={r.id}><td>{r.test_case_id} · v{r.test_case_version}</td><td className="num">{r.passed_evaluations} / {r.total_valid_evaluations}</td><td className="num">{pct(r.pass_rate)}</td><td className="num">{r.unique_students}</td><td><Review row={r} /></td></tr>)}</tbody>
        </table></div>
        <p className="muted small">{cases.data?.total} test-case versions. Valid attempts exclude missing, skipped and infrastructure evaluations. Error and timeout from learner code count as academic failures.</p>
      </Status>
    </section>}
  </>;
}

function Review({ row }: { row: AssessmentStat }) {
  return <><Tag kind={row.state === "NORMAL" ? "ok" : row.state === "INSUFFICIENT_DATA" ? undefined : "warn"}>{row.state.replaceAll("_", " ")}</Tag>
    {row.reasons.map((reason) => <div className="small" key={reason}>{reason}</div>)}
    {row.previous_pass_rate !== null && <div className="muted small">Previous window: {pct(row.previous_pass_rate)}</div>}
  </>;
}

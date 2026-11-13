import { useEffect, useState } from "react";
import { type AnalyticsClient, type AssessmentStat } from "../../analytics";
import { AnalyticsAccess, localDateTime, useAnalyticsPolling, utcDay } from "../../components/AnalyticsAccess";
import { HBars } from "../../components/charts";
import { Icon } from "../../components/Icon";
import { MeasuredBenchmarks, ReplayControl } from "../../components/ReplayAnalytics";
import { Badge, Btn, Callout, Card, Meter, PageHead, Pager, Status, Tile, type Tone } from "../../components/ui";
import { pct, relTime, useAction, useFetch } from "../../hooks";
import { CourseSelect, useInstructorCourse } from "./common";

const STATE: Record<string, [Tone, string]> = {
  NORMAL: ["good", "Normal"],
  INSUFFICIENT_DATA: ["neutral", "Insufficient data"],
  LOW_PASS_RATE: ["warn", "Low pass rate"],
  NEEDS_REVIEW: ["warn", "Needs review"],
  SUSPICIOUS_TEST_CASE: ["crit", "Suspicious test case"],
};
const FLAGGED = new Set(["LOW_PASS_RATE", "NEEDS_REVIEW", "SUSPICIOUS_TEST_CASE"]);
export const StateBadge = ({ state }: { state: string }) => {
  const [tone, label] = STATE[state] ?? ["neutral", state.replaceAll("_", " ").toLowerCase()];
  return <Badge tone={tone}>{label}</Badge>;
};

export function AssessmentHealth() {
  return (
    <>
      <PageHead br="BR4" title="Assessment health">
        Questions and test cases whose pass rate is abnormal: below the threshold, far below the other required tests, or dropping since the previous window.
      </PageHead>
      <AnalyticsAccess role="instructor">{(client, session) => <Results client={client} courses={session.courses}
        replay={session.replay} benchmarks={session.replay || session.classroom} />}</AnalyticsAccess>
    </>
  );
}

function Results({ client, courses, replay, benchmarks }: {
  client: AnalyticsClient; courses: { id: string; title: string }[]; replay?: boolean; benchmarks?: boolean;
}) {
  const [course, setCourse] = useInstructorCourse(courses);
  const [state, setState] = useState("");
  const [severity, setSeverity] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const filters = { status: state, severity, start: utcDay(start), end: utcDay(end, true), offset, limit: 20 };
  const q = useFetch(course ? () => client.questions(course, filters) : null, [client, course, state, severity, start, end, offset]);
  useAnalyticsPolling(q.reload);
  const requestRefresh = useAction(async () => {
    await client.refresh(course, filters.start, filters.end);
    await q.reload();
  });
  const publication = q.data?.materialization_status;
  const items = q.data?.items ?? [];
  const selected = items.find((r) => r.id === selectedId) ?? null;
  useEffect(() => {
    if (items.length && !items.some((r) => r.id === selectedId)) setSelectedId((items.find((r) => FLAGGED.has(r.state)) ?? items[0]).id);
  }, [items, selectedId]);
  function change(setter: (v: string) => void, v: string) { setter(v); setOffset(0); setSelectedId(null); }

  const flagged = items.filter((r) => FLAGGED.has(r.state));
  const high = flagged.filter((r) => r.severity === "HIGH").length;
  const latest = items.reduce<string | null>((a, r) => (!a || r.computed_at > a ? r.computed_at : a), null);
  return (
    <>
      <div className="filters">
        <CourseSelect courses={courses} value={course} onChange={(v) => change(setCourse, v)} />
        <label className="field">State
          <select className="select" value={state} onChange={(e) => change(setState, e.target.value)} aria-label="Assessment state">
            <option value="">All states</option>
            {Object.keys(STATE).map((s) => <option key={s} value={s}>{STATE[s][1]}</option>)}
          </select>
        </label>
        <label className="field">Severity
          <select className="select" value={severity} onChange={(e) => change(setSeverity, e.target.value)} aria-label="Assessment severity">
            <option value="">All severities</option>{["HIGH", "MEDIUM", "INFO"].map((s) => <option key={s} value={s}>{s[0] + s.slice(1).toLowerCase()}</option>)}
          </select>
        </label>
        <label className="field">From (UTC)<input className="input" type="date" value={start} onChange={(e) => change(setStart, e.target.value)} /></label>
        <label className="field">Through (UTC)<input className="input" type="date" value={end} onChange={(e) => change(setEnd, e.target.value)} /></label>
        {replay ? <ReplayControl client={client} refresh={q.reload} />
          : <Btn icon="refresh" disabled={!course || requestRefresh.pending}
              onClick={() => void requestRefresh.run()}>Refresh</Btn>}
      </div>
      {requestRefresh.error && <Callout tone="bad">{requestRefresh.error}</Callout>}
      {!replay && publication && <div className="toolbar" role="status">
        <Badge tone={publication === "SUCCEEDED" ? "good" : publication === "FAILED" ? "crit" : "warn"}>
          {publication === "SUCCEEDED" ? "Published" : publication === "NOT_REQUESTED" ? "Refresh needed" : publication.toLowerCase()}
        </Badge>
        {q.data?.stale && <span>Showing the last successful publication</span>}
        {q.data?.computed_at && <span>{q.data.engine} · {localDateTime(q.data.computed_at)}</span>}
        {q.data?.error && <span>{q.data.error}</span>}
      </div>}
      <div className="tiles">
        <Tile label="Question versions" value={q.data?.total ?? "–"} delta={q.data ? `${localDateTime(q.data.window_start)} – ${localDateTime(q.data.window_end)}` : undefined} />
        <Tile label="Flagged for review" value={q.data ? flagged.length : "–"}
          delta={q.data && <>{high > 0 && <Badge tone="crit">{high} high</Badge>}{flagged.length - high > 0 && <Badge tone="warn">{flagged.length - high} medium</Badge>}{flagged.length === 0 && "nothing abnormal"}</>} />
        <Tile label="Valid evaluations" value={q.data ? items.reduce((a, r) => a + r.total_valid_evaluations, 0).toLocaleString() : "–"} delta={items[0] ? `items need at least ${items[0].minimum_students} students` : undefined} />
        <Tile label="Last computed" value={<span style={{ fontSize: 20 }}>{latest ? relTime(latest) : "–"}</span>}
          delta={replay ? "from the latest replay stage" : "from live grade changes · refreshes every 5 s"} />
      </div>
      <div className="grid-3-2">
        <Card title="Questions" sub="Flagged items need a look. Select a question to see why and drill into its test cases."
          footer="Low pass rates identify assessments for instructor review. They do not prove a grading defect.">
          <Status loading={q.loading && !q.data} error={q.error} empty={q.data?.total === 0 ? "No evaluated questions match. Load the synthetic fixture or adjust your filters." : false}>
            <div className="table-wrap">
              <table className="t">
                <caption className="sr-only">Question pass rates and review state</caption>
                <thead><tr><th style={{ minWidth: 190 }}>Question</th><th className="r">Students</th><th>Pass rate</th><th className="r">Change</th><th>State</th></tr></thead>
                <tbody>
                  {items.map((r) => {
                    const delta = r.pass_rate !== null && r.previous_pass_rate !== null ? (r.pass_rate - r.previous_pass_rate) * 100 : null;
                    return (
                      <tr key={r.id} className="selectable" aria-selected={r.id === selectedId} onClick={() => setSelectedId(r.id)} style={{ cursor: "pointer" }}>
                        <td>
                          <button className="btn link" onClick={(e) => { e.stopPropagation(); setSelectedId(r.id); }} aria-pressed={r.id === selectedId}>{r.question_title ?? r.question_id} · v{r.question_version}</button>
                          <span className="sub">{r.assignment_title ?? r.assignment_id}</span>
                        </td>
                        <td className="r num">{r.unique_students}</td>
                        <td><Meter value={r.pass_rate} /></td>
                        <td className="r num small">{delta === null ? "–" : <span className={delta <= -30 ? "delta-bad" : undefined}>{delta > 0 ? "+" : delta < 0 ? "−" : ""}{Math.abs(delta).toFixed(1)}</span>}</td>
                        <td><StateBadge state={r.state} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pager offset={offset} total={q.data?.total ?? 0} onChange={setOffset} />
          </Status>
        </Card>
        {selected ? <Detail client={client} row={selected} window={{ start: q.data?.window_start, end: q.data?.window_end }} /> : <Card className="sticky"><p className="empty">Select a question to see its test cases.</p></Card>}
      </div>
      {benchmarks && <MeasuredBenchmarks client={client} requirement="BR4" />}
    </>
  );
}

function Detail({ client, row, window }: { client: AnalyticsClient; row: AssessmentStat; window: { start?: string; end?: string } }) {
  const cases = useFetch(() => client.cases(row.question_id, { version: row.question_version, start: window.start, end: window.end, limit: 100 }), [client, row.question_id, row.question_version, window.start, window.end]);
  useAnalyticsPolling(cases.reload);
  const caseRows = cases.data?.items ?? [];
  const threshold = caseRows[0]?.threshold;
  return (
    <section className="card sticky" aria-label="Selected question test cases">
      <div className="detail-head">
        <div>
          <p className="eyebrow">Question · {row.assignment_title ?? row.assignment_id}</p>
          <h2>{row.question_title ?? row.question_id} · v{row.question_version}</h2>
        </div>
        <div className="chips"><StateBadge state={row.state} /><span className="chip">{row.severity[0] + row.severity.slice(1).toLowerCase()} severity</span></div>
      </div>
      {row.reasons.length > 0 && <ul className="reason-list">{row.reasons.map((r) => <li key={r}><Icon name="arrow-right" /><span>{r}</span></li>)}</ul>}
      <dl className="spec">
        <dt>Passed / valid</dt><dd className="num">{row.passed_evaluations} / {row.total_valid_evaluations} ({pct(row.pass_rate, 1)})</dd>
        <dt>Students</dt><dd className="num">{row.unique_students}</dd>
        <dt>First / latest attempt</dt><dd className="num">{pct(row.first_attempt_pass_rate)} / {pct(row.latest_attempt_pass_rate)}</dd>
        <dt>Previous window</dt><dd className="num">{pct(row.previous_pass_rate, 1)}</dd>
        <dt>Invalid / infrastructure</dt><dd className="num">{row.invalid_evaluations} / {row.infrastructure_errors}</dd>
      </dl>
      <h3 className="section-title">Pass rate by test case</h3>
      <Status loading={cases.loading && !cases.data} error={cases.error} empty={cases.data?.total === 0 ? "No required test-case evaluations in this window." : false}>
        {threshold !== undefined && <p className="xs muted" style={{ marginBottom: 10 }}>Vertical line: {pct(threshold)} threshold</p>}
        <HBars refValue={threshold} rows={caseRows.map((c) => ({
          key: c.id, value: c.pass_rate, on: FLAGGED.has(c.state),
          title: `${c.test_case_id} · v${c.test_case_version}`,
          label: <>{FLAGGED.has(c.state) && <Icon name="alert" label={STATE[c.state]?.[1]} />}<span className="mono" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{c.test_case_id}</span></>,
        }))} />
        <div className="table-wrap mt">
          <table className="t">
            <thead><tr><th>Test</th><th className="r">Passed / valid</th><th className="r">Students</th><th>Strong cohort</th><th>Review</th></tr></thead>
            <tbody>
              {caseRows.map((c) => (
                <tr key={c.id}>
                  <td className="mono nowrap">{c.test_case_id} · v{c.test_case_version}</td>
                  <td className="r num">{c.passed_evaluations} / {c.total_valid_evaluations}</td>
                  <td className="r num">{c.unique_students}</td>
                  <td>{c.cohort_pass_rate == null ? "—" : `${pct(c.cohort_pass_rate)} (${c.cohort_students} students)`}</td>
                  <td><StateBadge state={c.state} />{c.reasons.map((r) => <div className="xs muted" key={r} style={{ marginTop: 4 }}>{r}</div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="xs muted" style={{ marginTop: 10 }}>Valid attempts exclude missing, skipped and infrastructure evaluations. Errors and timeouts from learner code count as failures.</p>
      </Status>
    </section>
  );
}

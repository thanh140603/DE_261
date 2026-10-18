import { useState } from "react";
import { analyticsApi, type StudentRisk } from "../analytics";
import { AnalyticsAccess, localDateTime, Pager, useAnalyticsPolling, utcDay } from "../components/AnalyticsAccess";
import { Btn, Panel, Select, Status, Tag, ViewHead } from "../components/ui";
import { pct, useAction, useFetch } from "../hooks";

export function AdvisorView() {
  return <>
    <ViewHead title="Advisor">Review learners who may need support, inspect the signals behind each risk score, and track interventions.</ViewHead>
    <AnalyticsAccess role="advisor">{(token, session) => <AdvisorResults token={token} courses={session.courses} />}</AnalyticsAccess>
  </>;
}

function AdvisorResults({ token, courses }: { token: string; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useState(courses[0]?.id ?? "");
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [alertOffset, setAlertOffset] = useState(0);
  const [student, setStudent] = useState("");
  const client = analyticsApi(token);
  const filters = { level, start: utcDay(start), end: utcDay(end, true), limit: 20 };
  const risks = useFetch(course ? () => client.risks(course, { ...filters, offset }) : null, [token, course, level, start, end, offset]);
  const alerts = useFetch(course ? () => client.alerts({ ...filters, course_id: course, status, offset: alertOffset }) : null, [token, course, level, status, start, end, alertOffset]);
  const detail = useFetch(student ? () => client.student(student, { course_id: course }) : null, [token, course, student]);
  const history = useFetch(student ? () => client.history(student, { course_id: course, limit: 50 }) : null, [token, course, student]);
  useAnalyticsPolling(risks.reload); useAnalyticsPolling(alerts.reload); useAnalyticsPolling(detail.reload); useAnalyticsPolling(history.reload);
  const action = useAction(async (id: string, kind: "acknowledge" | "resolve") => { await client.alertAction(id, kind); await alerts.reload(); });
  function change(setter: (value: string) => void, value: string) { setter(value); setOffset(0); setAlertOffset(0); setStudent(""); }
  return <>
    <div className="toolbar">
      <Select label="Advisor course" value={course} options={courses} onChange={(v) => change(setCourse, v)} render={(c) => c.title} />
      <label className="field"><span>Risk severity</span><select value={level} onChange={(e) => change(setLevel, e.target.value)}><option value="">All levels</option>{["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label className="field"><span>Alert status</span><select value={status} onChange={(e) => change(setStatus, e.target.value)}><option value="">All statuses</option>{["NEW", "ACKNOWLEDGED", "RESOLVED"].map((v) => <option key={v}>{v}</option>)}</select></label>
      <label className="field"><span>From (UTC)</span><input type="date" value={start} onChange={(e) => change(setStart, e.target.value)} /></label>
      <label className="field"><span>Through (UTC)</span><input type="date" value={end} onChange={(e) => change(setEnd, e.target.value)} /></label>
      <Btn onClick={() => { void risks.reload(); void alerts.reload(); void detail.reload(); void history.reload(); }}>Refresh risk data</Btn>
    </div>
    {risks.data && <p className="analytics-summary" aria-live="polite"><strong>{risks.data.summary.monitored} learners monitored</strong>
      {Object.entries(risks.data.summary.levels).map(([name, count]) => <span className="num" key={name}>{name}: {count}</span>)}
    </p>}
    <div className="grid wide">
      <Panel title="Learners to review" br="BR5">
        <p className="muted small">Rule-based points indicate support needs. They are not dropout probabilities. Records refresh every 5 seconds.</p>
        <Status loading={risks.loading} error={risks.error} empty={risks.data?.total === 0 ? "No learner risk records match. Check the filters or load the synthetic demonstration data." : false}>
          <div className="analytics-table"><table><thead><tr><th>Learner</th><th>Risk / 100</th><th>Activity: last / preceding 7 days</th><th>Required deadlines missed</th><th>Reasons</th><th>Evaluated</th></tr></thead>
            <tbody>{risks.data?.items.map((r) => <tr key={`${r.student_id}-${r.course_id}`}>
              <td><button className="btn" onClick={() => setStudent(r.student_id)} aria-pressed={student === r.student_id}>{r.student_id}</button></td>
              <td><strong className="num">{r.score}</strong> <RiskTag level={r.level} />{!r.eligible && <div className="muted small">Insufficient history or inactive</div>}</td>
              <td className="num">{r.features.activity_7d} / {r.features.activity_previous_7d}</td><td className="num">{r.features.missed_deadlines_14d}</td>
              <td>{r.reasons.map((s) => <div className="small" key={s.signal}>{s.reason} (+{s.points})</div>)}{r.reasons.length === 0 && <span className="muted">No risk signals</span>}</td>
              <td className="small num">{localDateTime(r.evaluated_at)}</td>
            </tr>)}</tbody>
          </table></div>
          <Pager offset={offset} total={risks.data?.total ?? 0} onChange={setOffset} />
        </Status>
      </Panel>
      <Panel title="Intervention alerts" br="BR5">
        {action.error && <p className="error" role="alert">{action.error}</p>}
        <Status loading={alerts.loading} error={alerts.error} empty={alerts.data?.total === 0 ? "No alerts match these filters. Alerts appear when an eligible learner crosses the configured threshold." : false}>
          <div className="analytics-table"><table><thead><tr><th>Learner / severity</th><th>Status</th><th>Reasons</th><th>Created / updated risk</th><th>Intervention</th></tr></thead>
            <tbody>{alerts.data?.items.map((a) => <tr key={a.id}>
              <td><button className="btn" onClick={() => setStudent(a.student_id)}>{a.student_id}</button><div><RiskTag level={a.level} /> <span className="num">{a.score} points</span></div></td>
              <td><Tag kind={a.status === "RESOLVED" ? "ok" : "warn"}>{a.status}</Tag><div className="muted small">{a.acknowledged_at && `Acknowledged ${localDateTime(a.acknowledged_at)}`}</div></td>
              <td>{a.reasons.map((r) => <div className="small" key={r.signal}>{r.reason}</div>)}</td>
              <td className="small num">{localDateTime(a.created_at)}<br />{localDateTime(a.evaluated_at)}</td>
              <td><div className="actions">
                <Btn onClick={() => void action.run(a.id, "acknowledge")} pending={action.pending} disabled={a.status !== "NEW"}>Acknowledge</Btn>
                <Btn onClick={() => void action.run(a.id, "resolve")} pending={action.pending} disabled={a.status === "RESOLVED"}>Resolve</Btn>
              </div>{a.resolved_at && <span className="muted small">Resolved {localDateTime(a.resolved_at)}</span>}</td>
            </tr>)}</tbody>
          </table></div>
          <Pager offset={alertOffset} total={alerts.data?.total ?? 0} onChange={setAlertOffset} />
        </Status>
      </Panel>
      {student && <Panel title={`Risk detail · ${student}`} br="BR5">
        <Status loading={detail.loading} error={detail.error}>
          {detail.data?.courses.map((r) => <div key={r.course_id}>
            <p><strong className="num">{r.score} / 100</strong> <RiskTag level={r.level} /> · {r.eligibility_reason}</p>
            <p className="muted small">Evaluated {localDateTime(r.evaluated_at)} · Persisted {localDateTime(r.computed_at)} · Window slide {r.policy.slide_seconds / 3600} hours</p>
            <dl className="kv analytics-detail"><dt>Recent / previous / 14-day activity</dt><dd className="num">{r.features.activity_7d} / {r.features.activity_previous_7d} / {r.features.activity_14d}</dd>
              <dt>Last meaningful activity</dt><dd>{localDateTime(r.features.last_activity_at)}</dd><dt>Due-assignment submission rate</dt><dd>{pct(r.features.submission_rate_14d)}</dd>
              <dt>Telemetry</dt><dd>{r.features.telemetry_available ? "Configured" : "Unavailable; engagement penalties disabled"}</dd>
            </dl>
          </div>)}
        </Status>
        <Status loading={history.loading} error={history.error} empty={history.data?.total === 0 ? "No risk history yet." : false}>
          <RiskTrend rows={[...(history.data?.items ?? [])].reverse()} />
          <p className="muted small">Most recent {history.data?.items.length ?? 0} of {history.data?.total ?? 0} risk observations; corrections at the same evaluation time remain in the audit history.</p>
        </Status>
      </Panel>}
    </div>
  </>;
}

function RiskTag({ level }: { level: string }) {
  return <Tag kind={level === "CRITICAL" || level === "HIGH" ? "bad" : level === "MEDIUM" ? "warn" : "ok"}>{level}</Tag>;
}

function RiskTrend({ rows }: { rows: StudentRisk[] }) {
  if (rows.length < 2) return <p className="empty">Two observations are needed to show a risk trend.</p>;
  const points = rows.map((r, i) => `${40 + i / (rows.length - 1) * 600},${130 - r.score}`).join(" ");
  return <figure className="risk-trend"><figcaption>Risk history · points out of 100</figcaption>
    <svg viewBox="0 0 680 170" role="img" aria-label={`Risk changed from ${rows[0].score} to ${rows[rows.length - 1].score} points across ${rows.length} observations`}>
      <line x1="40" x2="640" y1="130" y2="130" stroke="var(--border-strong)" />
      <text x="8" y="36" fill="var(--muted)" fontSize="13">100</text><text x="20" y="134" fill="var(--muted)" fontSize="13">0</text>
      <polyline points={points} fill="none" stroke="var(--green)" strokeWidth="2.5" />
      <text x="40" y="160" fill="var(--muted)" fontSize="12">{localDateTime(rows[0].evaluated_at)}</text>
      <text x="640" y="160" textAnchor="end" fill="var(--muted)" fontSize="12">{localDateTime(rows[rows.length - 1].evaluated_at)}</text>
    </svg>
  </figure>;
}

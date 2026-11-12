import { useEffect, useMemo, useState } from "react";
import { analyticsApi, type CoursePolicy, type DropoutAlert, type RiskPolicy, type StudentRisk } from "../analytics";
import { AnalyticsAccess, AnalyticsFreshness, localDateTime, useAnalyticsPolling, utcDay } from "../components/AnalyticsAccess";
import { LineChart, TipRow } from "../components/charts";
import { MeasuredBenchmarks, ReplayControl } from "../components/ReplayAnalytics";
import { Badge, Btn, Callout, Card, DataTable, PageHead, Pager, SelectField, Status, Tile, useToast, type Tone } from "../components/ui";
import { formatTime, initials, pct, relTime, useAction, useFetch } from "../hooks";

const LEVEL: Record<string, [Tone, string, string]> = {
  CRITICAL: ["crit", "Critical", "var(--critical)"],
  HIGH: ["serious", "High", "var(--serious)"],
  MEDIUM: ["warn", "Medium", "var(--warning)"],
  LOW: ["good", "Low", "var(--good)"],
};
const ALERT: Record<string, [Tone, string, string]> = {
  NEW: ["info", "bell", "New alert"], ACKNOWLEDGED: ["neutral", "check", "Acknowledged"], RESOLVED: ["good", "check", "Resolved"],
};
const SIGNAL: Record<string, [string, string, boolean]> = {
  inactivity: ["var(--s1)", "No activity", false],
  missed_deadlines: ["var(--s2)", "Missed deadlines", false],
  low_completion: ["var(--s3)", "Low submission rate", false],
  activity_decline: ["var(--s4)", "Activity decline", true],
};
const signal = (s: string): [string, string, boolean] => SIGNAL[s] ?? ["var(--ref)", s.replaceAll("_", " "), false];

export const LevelBadge = ({ level }: { level: string }) => {
  const [tone, label] = LEVEL[level] ?? ["neutral", level];
  return <Badge tone={tone}>{label}</Badge>;
};
const AlertBadge = ({ status }: { status: string }) => {
  const [tone, icon, label] = ALERT[status] ?? ["neutral", "info", status];
  return <Badge tone={tone} icon={icon}>{label}</Badge>;
};

export function AdvisorView() {
  return (
    <>
      <PageHead br="BR5" title="Learners to support">
        Risk points come from simple rules on activity, deadlines and submissions. They show who may need a check-in; they are not a dropout probability.
      </PageHead>
      <AnalyticsAccess role="advisor">{(token, session) => <Results token={token} courses={session.courses}
        replay={session.replay} benchmarks={session.replay || session.classroom} />}</AnalyticsAccess>
    </>
  );
}

function Results({ token, courses, replay, benchmarks }: {
  token: string; courses: { id: string; title: string }[]; replay?: boolean; benchmarks?: boolean;
}) {
  const [course, setCourse] = useState(courses[0]?.id ?? "");
  const [level, setLevel] = useState("");
  const [status, setStatus] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [offset, setOffset] = useState(0);
  const [student, setStudent] = useState("");
  const client = analyticsApi(token);
  const range = { start: utcDay(start), end: utcDay(end, true) };
  const risks = useFetch(course ? () => client.risks(course, { level, ...range, offset, limit: 20 }) : null, [token, course, level, start, end, offset]);
  const alerts = useFetch(course ? () => client.alerts({ course_id: course, level, ...range, limit: 100 }) : null, [token, course, level, start, end]);
  useAnalyticsPolling(risks.reload);
  useAnalyticsPolling(alerts.reload);
  const refresh = () => Promise.all([risks.reload(), alerts.reload()]);
  function change(setter: (v: string) => void, v: string) { setter(v); setOffset(0); setStudent(""); }

  // newest alert per learner in this course
  const alertOf = useMemo(() => {
    const m = new Map<string, DropoutAlert>();
    for (const a of alerts.data?.items ?? []) {
      const prev = m.get(a.student_id);
      if (!prev || a.created_at > prev.created_at) m.set(a.student_id, a);
    }
    return m;
  }, [alerts.data]);
  const rows = (risks.data?.items ?? []).filter((r) => !status || alertOf.get(r.student_id)?.status === status);
  useEffect(() => { if (rows.length && !rows.some((r) => r.student_id === student)) setStudent(rows[0].student_id); }, [rows, student]);
  const selected = rows.find((r) => r.student_id === student) ?? null;

  const all = alerts.data?.items ?? [];
  const open = all.filter((a) => a.status !== "RESOLVED");
  const levels = risks.data?.summary.levels ?? {};
  const levelTotal = Object.values(levels).reduce((a, b) => a + b, 0);
  return (
    <>
      <div className="filters">
        <SelectField label="Course" value={course} options={courses} onChange={(v) => change(setCourse, v)} render={(c) => c.title} valueOf={(c) => c.id} />
        <label className="field">Risk level
          <select className="select" value={level} onChange={(e) => change(setLevel, e.target.value)} aria-label="Risk severity">
            <option value="">All levels</option>{Object.keys(LEVEL).map((v) => <option key={v} value={v}>{LEVEL[v][1]}</option>)}
          </select>
        </label>
        <label className="field">Alert status
          <select className="select" value={status} onChange={(e) => change(setStatus, e.target.value)} aria-label="Alert status">
            <option value="">All</option>{Object.keys(ALERT).map((v) => <option key={v} value={v}>{ALERT[v][2].replace(" alert", "")}</option>)}
          </select>
        </label>
        <label className="field">From (UTC)<input className="input" type="date" value={start} onChange={(e) => change(setStart, e.target.value)} /></label>
        <label className="field">Through (UTC)<input className="input" type="date" value={end} onChange={(e) => change(setEnd, e.target.value)} /></label>
        {replay ? <ReplayControl token={token} refresh={refresh} />
          : <Btn icon="refresh" onClick={() => void refresh()}>Refresh</Btn>}
      </div>
      {!replay && <AnalyticsFreshness token={token} />}
      {!replay && course && <PolicyEditor key={course} token={token} course={course} />}
      <div className="tiles">
        <Tile label="Learners monitored" value={risks.data?.summary.monitored ?? "–"}
          delta={replay ? "from the latest replay stage" : "refreshes every 5 s"} />
        <Tile label="Open alerts" value={alerts.data ? open.length : "–"} delta={alerts.data ? `${open.filter((a) => a.status === "NEW").length} new · ${open.filter((a) => a.status === "ACKNOWLEDGED").length} acknowledged` : undefined} />
        <Tile label="Resolved alerts" value={alerts.data ? all.length - open.length : "–"} delta="in this period" />
        <div className="tile wide">
          <div className="tile-label">Risk levels now</div>
          {levelTotal > 0 ? (
            <>
              <div className="segbar" style={{ marginTop: 12 }} role="img" aria-label={Object.keys(LEVEL).map((k) => `${LEVEL[k][1]} ${levels[k] ?? 0}`).join(", ")}>
                {Object.keys(LEVEL).map((k) => (levels[k] ? <i key={k} style={{ flex: levels[k], background: LEVEL[k][2] }} /> : null))}
              </div>
              <div className="levels">{Object.keys(LEVEL).map((k) => <span key={k}><i className="sw-box" style={{ background: LEVEL[k][2] }} />{LEVEL[k][1]} {levels[k] ?? 0}</span>)}</div>
            </>
          ) : <p className="empty" style={{ padding: "8px 0 0" }}>No scored learners yet.</p>}
        </div>
      </div>
      <div className="grid-1-1">
        <Card title="Risk queue" sub="Highest points first. An alert opens at the policy threshold and is not repeated during the cooldown.">
          {alerts.error && <Callout tone="warn">Alerts could not be loaded: {alerts.error}</Callout>}
          <Status loading={risks.loading && !risks.data} error={risks.error} empty={risks.data && rows.length === 0 ? "No learner risk records match. Check the filters or load the synthetic demonstration data." : false}>
            <div className="queue" role="list" aria-label="Learners to review">
              {rows.map((r) => {
                const a = alertOf.get(r.student_id);
                const name = r.student_name ?? r.student_id;
                return (
                  <div role="listitem" key={`${r.student_id}-${r.course_id}`}>
                  <button className="queue-row" aria-pressed={r.student_id === student} aria-label={r.student_id} onClick={() => setStudent(r.student_id)}>
                    <span className="avatar sm">{initials(r.student_id)}</span>
                    <span style={{ minWidth: 0 }}>
                      <span className="queue-name">{name}{a && <AlertBadge status={a.status} />}</span>
                      <span className="queue-reasons">
                        {r.reasons.map((x) => { const [color, label] = signal(x.signal); return <span className="chip" key={x.signal}><i className="sw-box" style={{ background: color }} />{label}</span>; })}
                        {r.reasons.length === 0 && <span className="xs muted">{r.eligible ? "No risk signals" : "Not yet eligible"}</span>}
                      </span>
                    </span>
                    <span className="score-cell">
                      <b className="num">{r.score}</b><span className="xs muted"> / 100</span>
                      <div className="meter-track"><div className="meter-fill" style={{ width: `${r.score}%` }} /></div>
                      <div style={{ marginTop: 6 }}><LevelBadge level={r.level} /></div>
                    </span>
                  </button>
                  </div>
                );
              })}
            </div>
            <Pager offset={offset} total={risks.data?.total ?? 0} onChange={setOffset} />
          </Status>
        </Card>
        {selected ? <Detail token={token} course={course} row={selected} alert={alertOf.get(selected.student_id) ?? null} onAlertChange={() => void alerts.reload()} replay={replay} />
          : <Card className="sticky"><p className="empty">Select a learner to see the signals behind the score.</p></Card>}
      </div>
      {benchmarks && <MeasuredBenchmarks token={token} requirement="BR5" />}
    </>
  );
}

function Detail({ token, course, row, alert, onAlertChange, replay }: { token: string; course: string; row: StudentRisk; alert: DropoutAlert | null; onAlertChange: () => void; replay?: boolean }) {
  const client = analyticsApi(token);
  const toast = useToast();
  const replayAt = row.student_name ? row.evaluated_at : undefined;
  const detail = useFetch(() => client.student(row.student_id, { course_id: course }), [token, course, row.student_id, replayAt]);
  const history = useFetch(() => client.history(row.student_id, { course_id: course, limit: 50 }), [token, course, row.student_id, replayAt]);
  useAnalyticsPolling(detail.reload);
  useAnalyticsPolling(history.reload);
  const action = useAction(async (id: string, kind: "acknowledge" | "resolve") => {
    await client.alertAction(id, kind);
    onAlertChange();
    toast(kind === "acknowledge" ? "Alert acknowledged" : "Alert resolved");
  });
  const latest = detail.data?.courses.find((c) => c.course_id === course && c.student_id === row.student_id);
  const r = latest && (!replayAt || Date.parse(latest.evaluated_at) >= Date.parse(replayAt)) ? latest : row;
  const name = r.student_name ?? r.student_id;
  const points = [...(history.data?.items ?? [])].reverse();
  const f = r.features;
  return (
    <section className="card sticky" aria-label={`Risk detail for ${name}`}>
      <div className="detail-head">
        <div style={{ display: "flex", gap: 12, alignItems: "center", minWidth: 0 }}>
          <span className="avatar">{initials(name)}</span>
          <div style={{ minWidth: 0 }}><h2>{name}</h2><p className="small muted">{r.eligibility_reason}</p></div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", marginTop: 18 }}>
        <div><div className="tile-label">Risk points</div><div className="big-score"><b>{r.score}</b><span>/ 100</span></div></div>
        <div className="chips"><LevelBadge level={r.level} />{alert && <AlertBadge status={alert.status} />}</div>
      </div>
      <p className="xs muted" style={{ marginTop: 6 }}>Rule-based points that show who may need support, not a dropout probability. Evaluated {localDateTime(r.evaluated_at)} · policy v{r.policy_version ?? r.policy.version ?? 1}.</p>
      {r.reasons.length > 0 ? (
        <>
          <div className="segbar tall" style={{ marginTop: 14 }} role="img" aria-label={r.reasons.map((x) => `${signal(x.signal)[1]} ${x.points} points`).join(", ")}>
            {r.reasons.map((x) => { const [color, label, dark] = signal(x.signal); return <i key={x.signal} className={dark ? "dark-text" : undefined} style={{ width: `${x.points}%`, background: color }} title={`${label}: ${x.points} points`}>{x.points >= 12 ? x.points : ""}</i>; })}
            {r.score < 100 && <i className="rest" style={{ flex: 1 }} />}
          </div>
          <ul className="reason-list">
            {r.reasons.map((x) => <li key={x.signal}><i className="sw-box" style={{ background: signal(x.signal)[0], marginTop: 4 }} /><span style={{ flex: 1 }}>{x.reason}</span><b className="num">+{x.points}</b></li>)}
          </ul>
        </>
      ) : <div className="mt"><Callout tone="good">No risk signals: activity and submissions are on track.</Callout></div>}
      <div className="facts">
        <div><span>Activity, last / previous 7 days</span><b className="num">{f.activity_7d} / {f.activity_previous_7d} events</b></div>
        <div><span>Last meaningful activity</span><b>{f.last_activity_at ? `${localDateTime(f.last_activity_at)} (${relTime(f.last_activity_at)})` : "None recorded"}</b></div>
        <div><span>Required deadlines missed (14 days)</span><b className="num">{f.missed_deadlines_14d} of {f.due_assignments_14d}</b></div>
        <div><span>Due-assignment submission rate</span><b className="num">{pct(f.submission_rate_14d)}</b></div>
      </div>
      {!f.telemetry_available && <p className="xs muted" style={{ marginTop: 8 }}>Telemetry unavailable for this course; engagement penalties are disabled.</p>}

      <h3 className="section-title">Risk history · points out of 100</h3>
      <Status loading={history.loading && !history.data} error={history.error} empty={history.data && points.length < 2 ? "Two observations are needed to show a risk trend." : false}>
        <LineChart x={points.map((p) => replayAt ? formatTime(p.evaluated_at)
          : new Date(p.evaluated_at).toLocaleDateString([], { month: "short", day: "numeric" }))} yMax={100} yTicks={[0, 50, 100]} height={190}
          label={`Risk changed from ${points[0]?.score} to ${points[points.length - 1]?.score} points across ${points.length} observations`}
          refs={[{ y: r.policy.alert_threshold, label: `Alert ${r.policy.alert_threshold}` }]}
          series={[{ name: "Risk points", values: points.map((p) => p.score), color: "var(--s1)" }]}
          tip={(i) => <><div className="tt-title">{localDateTime(points[i].evaluated_at)}</div><TipRow color="var(--s1)" line label="Risk points" value={points[i].score} /><TipRow label="Level" value={LEVEL[points[i].level]?.[1] ?? points[i].level} /></>} />
        <DataTable head={["Evaluated", "Points", "Level"]} rows={points.map((p) => [
          replayAt ? formatTime(p.evaluated_at) : localDateTime(p.evaluated_at), p.score, LEVEL[p.level]?.[1] ?? p.level,
        ])} />
        <p className="xs muted" style={{ marginTop: 8 }}>Most recent {history.data?.items.length ?? 0} of {history.data?.total ?? 0} observations; corrections at the same evaluation time stay in the audit history.</p>
      </Status>

      {alert && (
        <>
          <div className="divider" />
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <div>
              <h3 style={{ fontSize: 13 }}>Alert · {alert.score} points</h3>
              <p className="xs muted">Opened {localDateTime(alert.created_at)}
                {alert.acknowledged_at && ` · acknowledged ${localDateTime(alert.acknowledged_at)}`}
                {alert.resolved_at && ` · resolved ${localDateTime(alert.resolved_at)}`}</p>
            </div>
            <div className="head-actions">
              <Btn size="sm" onClick={() => void action.run(alert.id, "acknowledge")} pending={action.pending} disabled={alert.status !== "NEW"}>Acknowledge</Btn>
              <Btn size="sm" variant="primary" onClick={() => void action.run(alert.id, "resolve")} pending={action.pending} disabled={alert.status === "RESOLVED"}>Resolve</Btn>
            </div>
          </div>
          {action.error && <div className="mt"><Callout tone="bad">{action.error}</Callout></div>}
          {!replay && <AlertNotes key={alert.id} token={token} alertId={alert.id} />}
        </>
      )}
    </section>
  );
}

function AlertNotes({ token, alertId }: { token: string; alertId: string }) {
  const [draft, setDraft] = useState("");
  const [requestKey, setRequestKey] = useState(() => crypto.randomUUID());
  const client = analyticsApi(token);
  const notes = useFetch(() => client.notes(alertId), [token, alertId]);
  const save = useAction(async () => {
    await client.addNote(alertId, draft.trim(), requestKey);
    setDraft("");
    setRequestKey(crypto.randomUUID());
    await notes.reload();
  });
  return <section className="mt" aria-label="Intervention notes">
    <h3 className="section-title">Intervention notes</h3>
    <Status loading={notes.loading && !notes.data} error={notes.error}>
      <ul className="reason-list">
        {notes.data?.map((note) => <li key={note.id}>
          <div><p>{note.note}</p><small>{note.actor} · {localDateTime(note.created_at)}</small></div>
        </li>)}
      </ul>
    </Status>
    <form onSubmit={(event) => { event.preventDefault(); if (draft.trim()) void save.run(); }}>
      <label className="field">Add intervention note
        <textarea className="input full" value={draft} maxLength={2000} rows={2}
          onChange={(event) => { setDraft(event.target.value); setRequestKey(crypto.randomUUID()); }} />
      </label>
      {save.error && <Callout tone="bad">{save.error}</Callout>}
      <Btn type="submit" size="sm" disabled={!draft.trim() || save.pending}>Save note</Btn>
    </form>
  </section>;
}

const POLICY_FIELDS: Record<keyof RiskPolicy, string> = {
  inactivity_points: "Inactivity points", missed_points: "Missed deadline points",
  completion_points: "Low submission points", decline_points: "Activity decline points",
  medium_threshold: "Medium threshold", high_threshold: "High threshold",
  critical_threshold: "Critical threshold", alert_threshold: "Alert threshold",
  cooldown_hours: "Cooldown (hours)", minimum_reference_events: "Minimum reference events",
};

function PolicyEditor({ token, course }: { token: string; course: string }) {
  const client = analyticsApi(token);
  const policy = useFetch(() => client.coursePolicy(course), [token, course]);
  const [draft, setDraft] = useState<CoursePolicy | null>(null);
  const save = useAction(async (version: CoursePolicy) => {
    await client.updatePolicy(course, version.version, version.parameters);
    setDraft(null);
    await policy.reload();
  });
  const current = draft ?? policy.data;
  return <details className="card">
    <summary>Course risk policy{policy.data && ` · v${policy.data.version}`}</summary>
    <Status loading={policy.loading} error={policy.error}>
      {current && <form className="mt" onSubmit={(event) => { event.preventDefault(); void save.run(current); }}>
        <div className="filters">{(Object.keys(POLICY_FIELDS) as (keyof RiskPolicy)[]).map((field) =>
          <label className="field" key={field}>{POLICY_FIELDS[field]}
            <input className="input" type="number" step={1} required
              min={field.includes("threshold") || field === "minimum_reference_events" ? 1 : 0}
              max={field.includes("threshold") || field.endsWith("_points") ? 100 : undefined}
              value={Number.isNaN(current.parameters[field]) ? "" : current.parameters[field]}
              onChange={(event) => setDraft({ ...current, parameters: { ...current.parameters, [field]: event.target.valueAsNumber } })} />
          </label>)}</div>
        {save.error && <Callout tone="bad">{save.error}</Callout>}
        <div className="toolbar">
          <Btn type="submit" size="sm" disabled={!draft || save.pending}>Save policy version</Btn>
          <Btn type="button" size="sm" onClick={() => { setDraft(null); void policy.reload(); }}>Reload policy</Btn>
        </div>
        <p className="xs muted">A saved version takes effect at the next completed evaluation boundary.</p>
      </form>}
    </Status>
  </details>;
}

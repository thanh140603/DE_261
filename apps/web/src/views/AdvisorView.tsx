import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatTime, useAction, useFetch } from "../hooks";
import { Btn, Panel, Select, Status, Tag, ViewHead } from "../components/ui";

export function AdvisorView() {
  const { overview, lastEventAt } = useStore();
  const learners = overview?.learners ?? [];
  const [learnerId, setLearnerId] = useState("");
  useEffect(() => { if (!learnerId && learners.length) setLearnerId(learners[0].id); }, [learners, learnerId]);

  const alerts = useFetch(() => api.advisor.alerts(), []);
  const risk = useFetch(learnerId ? () => api.advisor.risk(learnerId) : null, [learnerId]);
  useEffect(() => { void alerts.reload(); void risk.reload(); }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps

  const scenario = useAction(async () => {
    const r = await api.simulate.scenario("at_risk_learner");
    const id = typeof r.outcome.learner_id === "string" ? r.outcome.learner_id : null;
    if (id) setLearnerId(id);
    await alerts.reload();
    await risk.reload();
    return r;
  });

  const learner = learners.find((l) => l.id === learnerId);
  const courseId = learner?.course_ids[0];
  const cdc = useAction(async (kind: "deadline" | "grade" | "progress") => {
    if (!learner || !courseId) throw new Error("Pick a learner with a course");
    const lesson = overview?.courses.find((c) => c.id === courseId)?.lessons[0];
    const r =
      kind === "deadline"
        ? await api.simulate.cdc({ table: "grades", learner_id: learner.id, course_id: courseId, status: "missed" })
        : kind === "grade"
          ? await api.simulate.cdc({ table: "grades", learner_id: learner.id, course_id: courseId, score: 35 })
          : await api.simulate.cdc({ table: "lesson_progress", learner_id: learner.id, course_id: courseId, lesson_id: lesson?.id, percent_done: 80 });
    await risk.reload();
    await alerts.reload();
    return r;
  });

  return (
    <>
      <ViewHead title="Advisor">
        Advisors get an early warning when a learner is likely to drop out. Changes in the LMS database (progress,
        grades, enrollments) stream in as CDC and are scored over a sliding window.
      </ViewHead>
      <div className="grid">
        <Panel title="Drop-out alerts" br="BR5">
          <div className="actions">
            <Btn primary onClick={() => void scenario.run()} pending={scenario.pending}>Run scenario: at-risk learner</Btn>
          </div>
          {scenario.error && <div className="error">{scenario.error}</div>}
          {scenario.result && (
            <ol className="small" style={{ margin: "0 0 10px", paddingLeft: 18 }}>
              {scenario.result.steps.map((s, i) => <li key={i}><span className="muted num">{formatTime(s.at)}</span> {s.message}</li>)}
            </ol>
          )}
          <Status loading={alerts.loading && !alerts.data} error={alerts.error} empty={alerts.data && alerts.data.length === 0 ? "No alerts. Run the scenario, or mark a deadline missed for a learner." : false}>
            <div className="list">
              {alerts.data?.map((a, i) => (
                <button key={`${a.learner_id}-${a.course_id}-${i}`} className="item" style={{ textAlign: "left", cursor: "pointer", background: "var(--surface)" }} onClick={() => setLearnerId(a.learner_id)}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                    <strong>{a.learner_name}</strong>
                    <Tag kind="bad">risk {a.score.toFixed(2)}</Tag>
                  </div>
                  <div className="muted">{a.course_title}</div>
                  <div className="meta"><span className="num">{formatTime(a.at)}</span><span>{a.top_signals.join(", ")}</span></div>
                </button>
              ))}
            </div>
          </Status>
        </Panel>

        <Panel title="Learner risk" br="BR5">
          <div className="toolbar" style={{ margin: "0 0 10px" }}>
            <Select label="Learner" value={learnerId} options={learners} onChange={setLearnerId} render={(l) => `${l.name} (${l.id})`} />
          </div>
          <div className="actions">
            <Btn onClick={() => void cdc.run("deadline")} pending={cdc.pending} danger>Mark deadline missed</Btn>
            <Btn onClick={() => void cdc.run("grade")} pending={cdc.pending} danger>Lower a grade</Btn>
            <Btn onClick={() => void cdc.run("progress")} pending={cdc.pending}>Mark lesson 80% done</Btn>
          </div>
          {cdc.error && <div className="error">{cdc.error}</div>}
          {cdc.result?.risk && (
            <div className={cdc.result.risk.alerted ? "notice" : "ok"}>
              Change applied. New score {cdc.result.risk.score.toFixed(2)}{cdc.result.risk.alerted ? ", alert sent to the advisor." : ", below the alert threshold."}
            </div>
          )}
          <Status loading={risk.loading && !risk.data} error={risk.error} empty={risk.data && risk.data.courses.length === 0 ? "No risk profile yet for this learner. Apply a change above." : false}>
            {risk.data?.courses.map((c) => (
              <div key={c.course_id} style={{ marginBottom: 16 }}>
                <h3>{overview?.courses.find((x) => x.id === c.course_id)?.title ?? c.course_id}</h3>
                <div className="gauge">
                  <Gauge value={c.score} threshold={risk.data!.policy.alert_threshold} />
                  <div className="small">
                    <div>Score <strong className="num">{c.score.toFixed(2)}</strong> at {formatTime(c.computed_at)}</div>
                    <div className="muted">Threshold {risk.data!.policy.alert_threshold}, window {risk.data!.policy.window_days} d sliding by {risk.data!.policy.slide_days} d, cooldown {risk.data!.policy.cooldown_days >= 1 ? `${risk.data!.policy.cooldown_days} d` : `${Math.round(risk.data!.policy.cooldown_days * 1440)} min`}</div>
                    <div className="muted">Last alert {c.last_alert_at ? formatTime(c.last_alert_at) : "never"}</div>
                  </div>
                </div>
                <Spark history={c.history} threshold={risk.data!.policy.alert_threshold} />
                <table style={{ marginTop: 8 }}>
                  <thead><tr><th>Signal</th><th className="num">Weight</th><th>Observed</th></tr></thead>
                  <tbody>
                    {c.signals.map((s, i) => (
                      <tr key={i}><td>{s.kind.replaceAll("_", " ")}</td><td className="num">{s.weight.toFixed(2)}</td><td className="num">{formatTime(s.observed_at)}</td></tr>
                    ))}
                    {c.signals.length === 0 && <tr><td colSpan={3} className="muted">No signals in the window.</td></tr>}
                  </tbody>
                </table>
              </div>
            ))}
          </Status>
        </Panel>
      </div>
    </>
  );
}

function Gauge({ value, threshold }: { value: number; threshold: number }) {
  const r = 40, cx = 50, cy = 50;
  const arc = (from: number, to: number) => {
    const a = (t: number) => Math.PI * (1 - t);
    const x1 = cx + r * Math.cos(a(from)), y1 = cy - r * Math.sin(a(from));
    const x2 = cx + r * Math.cos(a(to)), y2 = cy - r * Math.sin(a(to));
    return `M${x1},${y1} A${r},${r} 0 ${to - from > 0.5 ? 1 : 0} 1 ${x2},${y2}`;
  };
  const tx = cx + (r + 6) * Math.cos(Math.PI * (1 - threshold)), ty = cy - (r + 6) * Math.sin(Math.PI * (1 - threshold));
  const color = value >= threshold ? "var(--red)" : value >= threshold * 0.6 ? "var(--amber)" : "var(--green)";
  return (
    <svg viewBox="0 0 100 58" width="140" role="img" aria-label={`Risk score ${value.toFixed(2)}`}>
      <path d={arc(0, 1)} stroke="var(--border)" strokeWidth="8" fill="none" />
      {value > 0 && <path d={arc(0, Math.min(1, value))} stroke={color} strokeWidth="8" fill="none" strokeLinecap="butt" />}
      <circle cx={tx} cy={ty} r="2.5" fill="var(--ink)" />
      <text x="50" y="52" textAnchor="middle" fontSize="14" fontWeight="700" fill="var(--ink)">{value.toFixed(2)}</text>
    </svg>
  );
}

function Spark({ history, threshold }: { history: { at: string; score: number }[]; threshold: number }) {
  if (history.length < 2) return <div className="muted small">Not enough history for a trend line.</div>;
  const W = 320, H = 50, P = 4;
  const pt = (i: number, s: number) => `${P + (i / (history.length - 1)) * (W - 2 * P)},${H - P - s * (H - 2 * P)}`;
  const ty = H - P - threshold * (H - 2 * P);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="50" role="img" aria-label="Risk score history">
      <line x1={P} x2={W - P} y1={ty} y2={ty} stroke="var(--red)" strokeDasharray="3 3" strokeWidth="1" />
      <path d={history.map((h, i) => `${i === 0 ? "M" : "L"}${pt(i, h.score)}`).join(" ")} fill="none" stroke="var(--blue)" strokeWidth="2" />
    </svg>
  );
}

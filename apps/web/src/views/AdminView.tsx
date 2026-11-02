import { useState } from "react";
import { analyticsApi } from "../analytics";
import { AnalyticsAccess, localDateTime } from "../components/AnalyticsAccess";
import { Btn, Panel, Select, Status, ViewHead } from "../components/ui";
import { formatDay, pct, useFetch } from "../hooks";

export function AdminView() {
  return (
    <>
      <ViewHead title="Admin">
        Organisation admins follow skill progress and completion for their own learners. Reports are built in the
        lakehouse from pseudonymised events, and any group smaller than the minimum cohort is hidden so nobody can be
        singled out.
      </ViewHead>
      <AnalyticsAccess role="admin" source="lakehouse">
        {(token, session) => <OrgProgress token={token} organisations={session.organisations} />}
      </AnalyticsAccess>
    </>
  );
}

function OrgProgress({ token, organisations }: { token: string; organisations: { id: string; name: string }[] }) {
  const [orgId, setOrgId] = useState(organisations[0]?.id ?? "");
  const [asOf, setAsOf] = useState("");
  const q = useFetch(orgId ? () => analyticsApi(token).skillProgress(orgId, { as_of: asOf }) : null, [token, orgId, asOf]);
  return (
    <>
      <div className="toolbar">
        <Select label="Organisation" value={orgId} options={organisations} onChange={setOrgId} render={(o) => o.name} />
        <label className="field"><span>Report as of (UTC)</span><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
        <Btn onClick={() => void q.reload()}>Refresh report</Btn>
      </div>
      <div className="grid wide">
        <Panel title="Skill progress and completion" br="BR6">
          <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.rows.length === 0 ? "No enrolments for this organisation yet." : false}>
            {q.data && (
              <>
                <div className="muted small" style={{ marginBottom: 8 }}>
                  Daily report for {formatDay(q.data.as_of)}, built {localDateTime(q.data.built_at)}. Rows with fewer
                  than {q.data.min_cohort} learners are hidden (k-anonymity).
                </div>
                <div className="analytics-table">
                  <table>
                    <thead><tr><th>Course</th><th>Skill</th><th className="num">Learners</th><th className="num">Completed</th><th>Completion</th><th>Average mastery</th></tr></thead>
                    <tbody>
                      {q.data.rows.map((r) => (
                        <tr key={r.course_id}>
                          <td>{r.course_title ?? r.course_id}</td>
                          <td>{r.skill ?? "–"}</td>
                          <td className="num">{r.cohort_size}</td>
                          {r.suppressed ? (
                            <td colSpan={3} className="muted">Hidden: fewer than {q.data!.min_cohort} learners</td>
                          ) : (
                            <>
                              <td className="num">{r.completed_learners ?? "–"}</td>
                              <td><Meter value={r.completion_rate} /></td>
                              <td><Meter value={r.avg_mastery} color="var(--blue)" /></td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="muted small">
                  Completion is the average share of course lessons finished. Mastery is the average test pass rate of
                  graded submissions; learners without graded work count as 0.
                </p>
              </>
            )}
          </Status>
        </Panel>
      </div>
    </>
  );
}

function Meter({ value, color }: { value: number | null; color?: string }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <div className="bar"><i style={{ width: `${(value ?? 0) * 100}%`, ...(color ? { background: color } : {}) }} /></div>
      <span className="num small">{pct(value)}</span>
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatDate, pct, useFetch } from "../hooks";
import { Panel, Select, Status, ViewHead } from "../components/ui";

export function AdminView() {
  const { overview, lastEventAt } = useStore();
  const orgs = overview?.organisations ?? [];
  const [orgId, setOrgId] = useState("");
  useEffect(() => { if (!orgId && orgs.length) setOrgId(orgs[0].id); }, [orgs, orgId]);
  const q = useFetch(orgId ? () => api.admin.progress(orgId) : null, [orgId]);
  useEffect(() => { void q.reload(); }, [lastEventAt]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <ViewHead title="Admin">
        Organisation admins follow skill progress and completion for their own learners. Reports are built from
        pseudonymised events, and any group smaller than the minimum cohort is hidden so nobody can be singled out.
      </ViewHead>
      <div className="toolbar">
        <Select label="Organisation" value={orgId} options={orgs} onChange={setOrgId} render={(o) => o.name} />
      </div>
      <div className="grid wide">
        <Panel title="Skill progress and completion" br="BR6">
          <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.rows.length === 0 ? "No enrolments for this organisation yet." : false}>
            {q.data && (
              <>
                <div className="muted small" style={{ marginBottom: 8 }}>
                  As of {formatDate(q.data.as_of)}. Rows with fewer than {q.data.min_cohort} learners are hidden (k-anonymity).
                </div>
                <table>
                  <thead><tr><th>Course</th><th>Skill</th><th className="num">Learners</th><th>Completion</th><th>Average mastery</th></tr></thead>
                  <tbody>
                    {q.data.rows.map((r) => (
                      <tr key={`${r.course_id}-${r.skill}`}>
                        <td>{r.course_title}</td>
                        <td>{r.skill}</td>
                        <td className="num">{r.cohort_size}</td>
                        {r.suppressed ? (
                          <td colSpan={2} className="muted">Hidden: fewer than {q.data!.min_cohort} learners</td>
                        ) : (
                          <>
                            <td><div style={{ display: "flex", gap: 8, alignItems: "center" }}><div className="bar"><i style={{ width: `${(r.completion_rate ?? 0) * 100}%` }} /></div><span className="num small">{pct(r.completion_rate)}</span></div></td>
                            <td><div style={{ display: "flex", gap: 8, alignItems: "center" }}><div className="bar"><i style={{ width: `${(r.avg_mastery ?? 0) * 100}%`, background: "var(--blue)" }} /></div><span className="num small">{pct(r.avg_mastery)}</span></div></td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </Status>
        </Panel>
      </div>
    </>
  );
}

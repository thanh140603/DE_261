import { useState } from "react";
import { analyticsApi, type SkillProgress } from "../analytics";
import { AnalyticsAccess, localDateTime } from "../components/AnalyticsAccess";
import { HBars } from "../components/charts";
import { Icon } from "../components/Icon";
import { Badge, Btn, Callout, Card, Meter, PageHead, SelectField, Status, Tile } from "../components/ui";
import { formatDay, humanize, useFetch } from "../hooks";

export function AdminView() {
  return (
    <>
      <PageHead eyebrow="Org admin" br="BR6" title="Organisation progress">
        Skill progress and course completion for your organisation's learners. Built daily in the lakehouse from pseudonymised data.
      </PageHead>
      <AnalyticsAccess role="admin" source="lakehouse">
        {(token, session) => <Progress token={token} organisations={session.organisations} />}
      </AnalyticsAccess>
    </>
  );
}

function exportCsv(d: SkillProgress) {
  const cell = (v: string | number | null) => (v === null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replaceAll('"', '""')}"` : String(v));
  const lines = [["course_id", "course_title", "skill", "learners", "completed_learners", "completion_rate", "avg_mastery"].join(",")];
  for (const r of d.rows) {
    lines.push([r.course_id, r.course_title, r.skill, r.suppressed ? `<${d.min_cohort}` : r.cohort_size, r.suppressed ? null : r.completed_learners,
      r.suppressed ? null : r.completion_rate, r.suppressed ? null : r.avg_mastery].map(cell).join(","));
  }
  const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url; a.download = `org-progress-${d.organisation_id}-${d.as_of.slice(0, 10)}.csv`; a.click();
  URL.revokeObjectURL(url);
}

function Progress({ token, organisations }: { token: string; organisations: { id: string; name: string }[] }) {
  const [orgId, setOrgId] = useState(organisations[0]?.id ?? "");
  const [asOf, setAsOf] = useState("");
  const q = useFetch(orgId ? () => analyticsApi(token).skillProgress(orgId, { as_of: asOf }) : null, [token, orgId, asOf]);
  const d = q.data;
  const shown = d?.rows.filter((r) => !r.suppressed) ?? [];
  const weighted = (k: "completion_rate" | "avg_mastery") => {
    const n = shown.reduce((a, r) => a + r.cohort_size, 0);
    return n ? shown.reduce((a, r) => a + (r[k] ?? 0) * r.cohort_size, 0) / n : null;
  };
  const skills = (() => {
    const m = new Map<string, { n: number; s: number }>();
    for (const r of shown) {
      const k = r.skill ?? "Other";
      const v = m.get(k) ?? { n: 0, s: 0 };
      m.set(k, { n: v.n + r.cohort_size, s: v.s + (r.avg_mastery ?? 0) * r.cohort_size });
    }
    return [...m.entries()].map(([k, v]) => ({ key: k, value: v.s / v.n, n: v.n })).sort((a, b) => b.value - a.value);
  })();
  const pctOrDash = (v: number | null) => (v === null ? "–" : `${Math.round(v * 100)}%`);
  return (
    <>
      <div className="filters">
        <SelectField label="Organisation" value={orgId} options={organisations} onChange={setOrgId} render={(o) => o.name} valueOf={(o) => o.id} />
        <label className="field">Report as of (UTC)<input className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
        <Btn icon="refresh" onClick={() => void q.reload()}>Refresh</Btn>
        <Btn icon="download" onClick={() => d && exportCsv(d)} disabled={!d}>Export CSV</Btn>
      </div>
      <div style={{ marginBottom: 16 }}>
        <Callout tone="neutral" icon="shield"><b>Privacy protection.</b> Any group with fewer than {d?.min_cohort ?? 5} learners is hidden so no individual can be singled out. Learner names never appear in this report.</Callout>
      </div>
      <Status loading={q.loading && !d} error={q.error} empty={d && d.rows.length === 0 ? "No enrolments for this organisation yet." : false}>
        {d && (
          <>
            <div className="tiles">
              <Tile label="Courses reported" value={<>{shown.length} <small>of {d.rows.length}</small></>} delta={`${d.rows.length - shown.length} hidden for privacy`} />
              <Tile label="Learners in reported courses" value={shown.reduce((a, r) => a + r.cohort_size, 0).toLocaleString()} delta="enrolments, not unique people" />
              <Tile label="Average completion" value={pctOrDash(weighted("completion_rate"))} delta="weighted by learners" />
              <Tile label="Average mastery" value={pctOrDash(weighted("avg_mastery"))} delta="test pass rate" />
            </div>
            <div className="grid-2-1">
              <Card title="Courses" sub={`Report for ${formatDay(d.as_of)}, built ${localDateTime(d.built_at)}.`}
                footer="Completion is the average share of a course's lessons finished. Mastery is the average test pass rate of graded submissions; learners without graded work count as 0.">
                <div className="table-wrap">
                  <table className="t">
                    <thead><tr><th style={{ minWidth: 180 }}>Course</th><th className="r">Learners</th><th className="r">Completed</th><th>Completion</th><th>Mastery</th></tr></thead>
                    <tbody>
                      {d.rows.map((r) => (
                        <tr key={r.course_id}>
                          <td><span className="strong">{r.course_title ?? r.course_id}</span><span className="sub">{humanize(r.skill)}</span></td>
                          {r.suppressed ? (
                            <>
                              <td className="r small muted nowrap">Fewer than {d.min_cohort}</td>
                              <td colSpan={3}><Badge tone="neutral" icon="lock">Hidden: fewer than {d.min_cohort} learners</Badge></td>
                            </>
                          ) : (
                            <>
                              <td className="r num">{r.cohort_size}</td>
                              <td className="r num">{r.completed_learners ?? "–"}</td>
                              <td><Meter value={r.completion_rate} /></td>
                              <td><Meter value={r.avg_mastery} /></td>
                            </>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title="Average mastery by skill" sub={`Only groups of ${d.min_cohort} or more learners.`}>
                {skills.length > 0
                  ? <HBars fmt={(v) => `${Math.round(v * 100)}%`} rows={skills.map((s) => ({ key: s.key, label: humanize(s.key), value: s.value, on: true, title: `${s.n} learners` }))} />
                  : <Callout tone="neutral" icon="shield">Every group in {d.organisation_name ?? "this organisation"} has fewer than {d.min_cohort} learners, so nothing can be shown yet.</Callout>}
                <p className="xs muted" style={{ marginTop: 12, display: "flex", gap: 6 }}><Icon name="info" />Weighted by the number of learners in each course.</p>
              </Card>
            </div>
          </>
        )}
      </Status>
    </>
  );
}

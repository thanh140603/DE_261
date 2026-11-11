import { useMemo, useState } from "react";
import { analyticsApi } from "../../analytics";
import { AnalyticsAccess, localDateTime, useAnalyticsPolling } from "../../components/AnalyticsAccess";
import { LineChart, MiniLine, TipRow } from "../../components/charts";
import { Badge, Btn, Card, DataTable, PageHead, Status, Tile } from "../../components/ui";
import { formatDay, pct, useFetch } from "../../hooks";
import { CourseSelect, useInstructorCourse } from "./common";

const shortDay = (d: string) => new Date(`${d.slice(0, 10)}T00:00:00Z`).toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });

export function EngagementTrend() {
  return (
    <>
      <PageHead br="BR8" title="Engagement trend">
        Weekly engagement per learner compared with the course average. Learners appear by pseudonym, never by name.
      </PageHead>
      <AnalyticsAccess role="instructor" source="lakehouse">{(token, session) => <Trend token={token} courses={session.courses} />}</AnalyticsAccess>
    </>
  );
}

function Trend({ token, courses }: { token: string; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useInstructorCourse(courses);
  const [asOf, setAsOf] = useState("");
  const [showAll, setShowAll] = useState(false);
  const q = useFetch(course ? () => analyticsApi(token).engagementTrend(course, { as_of: asOf }) : null, [token, course, asOf]);
  useAnalyticsPolling(q.reload);
  const d = q.data;
  const live = d?.live ?? null;
  const n = d?.course_avg.length ?? 0;
  const sorted = useMemo(() => [...(d?.learners ?? [])].sort((a, b) => Number(b.declining) - Number(a.declining)), [d]);
  const shown = showAll ? sorted : sorted.filter((l) => l.declining);
  const max = useMemo(() => Math.max(1, ...(d?.learners.flatMap((l) => l.scores) ?? []), ...(d?.course_avg ?? [])), [d]);
  const yMax = Math.max(2, Math.ceil(max / 2) * 2); // small multiples share the learners' scale
  const avgMax = Math.max(2, Math.ceil((Math.max(0, ...(d?.course_avg ?? [])) * 1.2) / 2) * 2);
  const activeLast = d ? d.learners.filter((l) => (l.scores[n - 1] ?? 0) > 0).length : 0;
  const activePrev = d ? d.learners.filter((l) => (l.scores[n - 2] ?? 0) > 0).length : 0;
  const avgDelta = n > 1 && d ? d.course_avg[n - 1] - d.course_avg[n - 2] : null;
  const liveCount = live ? Object.keys(live.scores).length : 0;
  const newToday = live && d ? Object.keys(live.scores).filter((p) => !d.learners.some((l) => l.learner_pseudonym === p)).length : 0;

  return (
    <>
      <div className="filters">
        <CourseSelect courses={courses} value={course} onChange={setCourse} />
        <label className="field">Trend as of (UTC)<input className="input" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
      </div>
      <Status loading={q.loading && !d} error={q.error} empty={d && d.learners.length === 0 ? "No learner activity in these weeks." : false}>
        {d && (
          <>
            <div className="tiles">
              <Tile label="Active learners last week" value={activeLast} delta={n > 1 ? <><span className={activeLast < activePrev ? "delta-bad" : "delta-good"}>{activeLast >= activePrev ? "+" : "−"}{Math.abs(activeLast - activePrev)}</span> vs the week before</> : undefined} />
              <Tile label="Course average" value={<>{d.course_avg[n - 1]?.toFixed(1) ?? "–"} <small>pts</small></>} delta={avgDelta !== null ? <><span className={avgDelta < 0 ? "delta-bad" : "delta-good"}>{avgDelta >= 0 ? "+" : "−"}{Math.abs(avgDelta).toFixed(1)}</span> vs the week before</> : undefined} />
              <Tile label="Declining learners" value={d.declining_count} delta={`down ${pct(d.decline_ratio)}+ two weeks running`} />
              <Tile label="Active today" value={live ? liveCount : "–"} delta={live && liveCount > 0 ? <><Badge tone="info" icon="activity">Live</Badge> avg {live.course_avg?.toFixed(1) ?? "–"} pts so far</> : "no streamed activity yet"} />
            </div>
            <Card title="Course average engagement" sub={`${d.week_starts.length} weekly windows from ${formatDay(d.week_starts[0])} to ${formatDay(d.as_of)}, built ${localDateTime(d.built_at)}.`}>
              {live && (liveCount > 0 ? (
                <p className="small" style={{ marginBottom: 8 }} aria-live="polite">
                  <Badge tone="info" icon="activity">Live</Badge> Today ({formatDay(live.day)}) so far: {liveCount} active learner{liveCount === 1 ? "" : "s"}, average {live.course_avg?.toFixed(1) ?? "–"} points{newToday ? `, ${newToday} not yet in the weekly trend` : ""}. Updated {localDateTime(live.updated_at)}.
                </p>
              ) : <p className="small muted" style={{ marginBottom: 8 }}>Today ({formatDay(live.day)}): no streamed activity yet.</p>)}
              <LineChart x={d.week_starts.map(shortDay)} yMax={avgMax} yTicks={[0, avgMax / 2, avgMax]} yFmt={(v) => (v % 1 ? v.toFixed(1) : String(v))} height={230} endLabel
                label={`Course average engagement over ${n} weeks, latest ${d.course_avg[n - 1]?.toFixed(1)} points`}
                series={[{ name: "Course average", values: d.course_avg, color: "var(--s1)", wash: true }]}
                tip={(i) => <><div className="tt-title">Week of {shortDay(d.week_starts[i])}</div><TipRow color="var(--s1)" line label="Course average" value={`${d.course_avg[i].toFixed(1)} pts`} /><TipRow label="Active learners" value={d.learners.filter((l) => (l.scores[i] ?? 0) > 0).length} /></>} />
              <DataTable head={["Week of", "Course average (pts)", "Active learners"]} rows={d.week_starts.map((w, i) => [formatDay(w), d.course_avg[i].toFixed(1), d.learners.filter((l) => (l.scores[i] ?? 0) > 0).length])} />
            </Card>
            <Card className="mt" title={<>{showAll ? "All learners" : "Declining learners"} {!showAll && <Badge tone="crit" icon="trend-down">{d.declining_count}</Badge>}</>}
              sub={`Declining: score down at least ${pct(d.decline_ratio)} in each of the last two weeks. Same scale in every panel.`}
              actions={<div className="legend"><span className="key"><span className="sw-line" style={{ background: "var(--s1)" }} />Learner</span><span className="key"><span className="sw-line" style={{ background: "var(--ref)" }} />Course average</span></div>}>
              {shown.length === 0 && <p className="empty">No learner is declining in this period.</p>}
              <div className="minis">
                {shown.map((l) => {
                  const last = l.scores[l.scores.length - 1] ?? 0;
                  const before = l.scores[l.scores.length - 3];
                  return (
                    <div className="mini" key={l.learner_pseudonym}>
                      <div className="mini-top">
                        <span className="mono strong" title={l.learner_pseudonym}>{l.learner_pseudonym.slice(0, 11)}</span>
                        {l.declining && <Badge tone="crit" icon="trend-down">Declining</Badge>}
                      </div>
                      <MiniLine values={l.scores} reference={d.course_avg} max={yMax} label={`Engagement of ${l.learner_pseudonym}: latest week ${last.toFixed(1)} points`} />
                      <div className="xs muted num">
                        Last week {last.toFixed(1)} pts{before ? ` (${Math.round((last / before - 1) * 100)}% in 2 wks)` : ""}
                        {live ? ` · today ${(live.scores[l.learner_pseudonym] ?? 0).toFixed(1)}` : ""}
                      </div>
                    </div>
                  );
                })}
              </div>
              {sorted.length > shown.length || showAll ? (
                <div className="actions"><Btn onClick={() => setShowAll(!showAll)}>{showAll ? "Show declining learners only" : `Show all ${sorted.length} learners`}</Btn></div>
              ) : null}
            </Card>
          </>
        )}
      </Status>
    </>
  );
}

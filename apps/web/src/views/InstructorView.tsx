import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatDate, formatTime, pct, useAction, useFetch } from "../hooks";
import { Btn, Panel, Select, Status, Tag, ViewHead } from "../components/ui";
import type { PublishResult } from "../types";

export function InstructorView() {
  const { overview, lastEventAt } = useStore();
  const courses = overview?.courses ?? [];
  const [courseId, setCourseId] = useState("");
  useEffect(() => { if (!courseId && courses.length) setCourseId(courses[0].id); }, [courses, courseId]);
  const course = courses.find((c) => c.id === courseId) ?? null;
  return (
    <>
      <ViewHead title="Instructor">
        Instructors spot questions and test cases that fail abnormally often, see where learners pause and rewind in a
        video, follow engagement over time, and trust that caches and search stay in sync when they change content.
      </ViewHead>
      <div className="toolbar">
        <Select label="Course" value={courseId} options={courses} onChange={setCourseId} render={(c) => c.title} />
      </div>
      {course && (
        <div className="grid">
          <Assessments courseId={course.id} tick={lastEventAt} />
          <Heatmap course={course} tick={lastEventAt} />
          <EngagementPanel courseId={course.id} tick={lastEventAt} />
          <ContentSync course={course} />
        </div>
      )}
    </>
  );
}

function Assessments({ courseId, tick }: { courseId: string; tick: number }) {
  const q = useFetch(() => api.instructor.assessments(courseId), [courseId]);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const scenario = useAction(async () => { const r = await api.simulate.scenario("broken_test_case"); await q.reload(); return r; });
  return (
    <Panel title="Assessment health" br="BR4">
      <div className="actions">
        <Btn onClick={() => void scenario.run()} pending={scenario.pending}>Run scenario: broken test case</Btn>
      </div>
      {scenario.error && <div className="error">{scenario.error}</div>}
      {scenario.result && <div className="notice">{scenario.result.steps.map((s) => s.message).join(" ")}</div>}
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "No graded submissions for this course yet. Submit code as a learner or run the scenario." : false}>
        <table>
          <thead><tr><th>Assignment</th><th>Item</th><th className="num">Attempts</th><th>Pass rate</th><th className="num">Median</th><th></th></tr></thead>
          <tbody>
            {q.data?.map((r) => (
              <tr key={`${r.assignment_id}-${r.item_id}`} className={r.is_anomalous ? "anomalous" : undefined}>
                <td>{r.assignment_title}</td>
                <td>{r.item_id}</td>
                <td className="num">{r.attempts}</td>
                <td>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <div className={`bar${r.is_anomalous ? " warn" : ""}`}><i style={{ width: `${r.pass_rate * 100}%` }} /></div>
                    <span className="num small">{pct(r.pass_rate)}</span>
                  </div>
                </td>
                <td className="num">{pct(r.assignment_median_pass_rate)}</td>
                <td>{r.is_anomalous && <Tag kind="warn">Far below the assignment median, check the test case</Tag>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Status>
    </Panel>
  );
}

function Heatmap({ course, tick }: { course: { id: string; lessons: { id: string; title: string; content_id: string }[] }; tick: number }) {
  const lessons = useMemo(() => course.lessons.map((l) => ({ id: l.content_id, title: l.title })), [course]);
  const [contentId, setContentId] = useState("");
  useEffect(() => { setContentId(lessons[0]?.id ?? ""); }, [lessons]);
  const q = useFetch(contentId ? () => api.instructor.heatmap(contentId) : null, [contentId]);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const burst = useAction(async () => { const r = await api.simulate.burst(200); await q.reload(); return r; });
  const [hover, setHover] = useState<number | null>(null);
  const max = useMemo(() => Math.max(1, ...(q.data?.buckets.map((b) => b.play + b.pause + b.seek) ?? [1])), [q.data]);
  const step = q.data ? Math.max(1, Math.ceil(q.data.buckets.length / 240)) : 1;
  const buckets = useMemo(() => {
    if (!q.data) return [];
    const out: { second: number; play: number; pause: number; seek: number; learners: number }[] = [];
    for (let i = 0; i < q.data.buckets.length; i += step) {
      const slice = q.data.buckets.slice(i, i + step);
      out.push({
        second: slice[0].second,
        play: slice.reduce((a, b) => a + b.play, 0),
        pause: slice.reduce((a, b) => a + b.pause, 0),
        seek: slice.reduce((a, b) => a + b.seek, 0),
        learners: Math.max(...slice.map((b) => b.learners)),
      });
    }
    return out;
  }, [q.data, step]);
  const scale = max * step;
  const h = hover !== null ? buckets[hover] : null;
  return (
    <Panel title="Video heatmap" br="BR7">
      <div className="toolbar" style={{ margin: "0 0 10px" }}>
        <Select label="Lesson video" value={contentId} options={lessons} onChange={setContentId} render={(l) => l.title} />
        <Btn onClick={() => void burst.run()} pending={burst.pending}>Simulate 200 viewing events</Btn>
      </div>
      {burst.error && <div className="error">{burst.error}</div>}
      <Status loading={q.loading && !q.data} error={q.error}>
        {q.data && (
          <>
            <div className="muted small" style={{ marginBottom: 6 }}>
              {q.data.title}, {q.data.duration_sec} s{step > 1 ? `, ${step} s per column` : ""}
            </div>
            <div className="heat" onMouseLeave={() => setHover(null)}>
              {h && <div className="tip" style={{ left: `${(hover! / buckets.length) * 100}%` }}>{h.second}s: {h.play} play, {h.pause} pause, {h.seek} seek, {h.learners} learners</div>}
              {buckets.map((b, i) => {
                const total = b.play + b.pause + b.seek;
                return (
                  <div className="col" key={b.second} onMouseEnter={() => setHover(i)} title={`${b.second}s`}>
                    {total === 0 ? <i style={{ height: 1, background: "var(--border)" }} /> : (
                      <>
                        <i className="play" style={{ height: `${(b.play / scale) * 100}%` }} />
                        <i className="pause" style={{ height: `${(b.pause / scale) * 100}%` }} />
                        <i className="seek" style={{ height: `${(b.seek / scale) * 100}%` }} />
                      </>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="legend">
              <span><i style={{ background: "var(--green)" }} />play</span>
              <span><i style={{ background: "var(--amber)" }} />pause</span>
              <span><i style={{ background: "var(--red)" }} />seek (rewind or skip)</span>
              <span className="muted">Dense pause and seek columns mark confusing moments.</span>
            </div>
          </>
        )}
      </Status>
    </Panel>
  );
}

function EngagementPanel({ courseId, tick }: { courseId: string; tick: number }) {
  const q = useFetch(() => api.instructor.engagement(courseId), [courseId]);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const W = 320, H = 90, P = 6;
  const max = useMemo(() => Math.max(1, ...(q.data?.learners.flatMap((l) => l.scores) ?? []), ...(q.data?.course_avg ?? [])), [q.data]);
  const path = (scores: number[]) => {
    const n = scores.length;
    if (n === 0) return "";
    return scores.map((s, i) => `${i === 0 ? "M" : "L"}${P + (i / Math.max(1, n - 1)) * (W - 2 * P)},${H - P - (s / max) * (H - 2 * P)}`).join(" ");
  };
  return (
    <Panel title="Engagement trend" br="BR8">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.learners.length === 0 ? "No activity windows yet. Start the simulator on the Pipeline page." : false}>
        {q.data && (
          <>
            <div className="muted small" style={{ marginBottom: 8 }}>
              {q.data.windows.length} windows, {formatDate(q.data.windows[0]?.start)} to {formatDate(q.data.windows[q.data.windows.length - 1]?.end)}. Learners are shown by pseudonym.
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
              {q.data.learners.map((l) => (
                <div key={l.pseudonym} className="item" style={{ padding: 8, borderColor: l.declining ? "var(--red)" : undefined }}>
                  <div className="small" style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="mono">{l.pseudonym.slice(0, 10)}</span>
                    {l.declining && <Tag kind="bad">declining</Tag>}
                  </div>
                  <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="70" role="img" aria-label={`Engagement of ${l.pseudonym}`}>
                    <path d={path(q.data!.course_avg)} fill="none" stroke="var(--border-strong)" strokeWidth="2" strokeDasharray="4 3" />
                    <path d={path(l.scores)} fill="none" stroke={l.declining ? "var(--red)" : "var(--green)"} strokeWidth="2.5" />
                  </svg>
                  <div className="muted small num">latest {l.scores[l.scores.length - 1]?.toFixed(1) ?? "–"}</div>
                </div>
              ))}
            </div>
            <div className="legend"><span><i style={{ background: "var(--border-strong)" }} />course average</span><span><i style={{ background: "var(--green)" }} />learner</span></div>
          </>
        )}
      </Status>
    </Panel>
  );
}

function ContentSync({ course }: { course: { id: string; lessons: { id: string; title: string; content_id: string }[] } }) {
  const lessons = useMemo(() => course.lessons.map((l) => ({ id: l.content_id, title: l.title })), [course]);
  const [contentId, setContentId] = useState("");
  useEffect(() => { setContentId(lessons[0]?.id ?? ""); }, [lessons]);
  const q = useFetch(contentId ? () => api.instructor.content(contentId) : null, [contentId]);
  const [body, setBody] = useState("Joins combine rows from two tables.\n\nAn inner join keeps only matching rows. A left join keeps every row from the left table.\n\nUse the ON clause to state the matching columns.");
  const [last, setLast] = useState<PublishResult | null>(null);
  const publish = useAction(async () => { const r = await api.instructor.publish(contentId, body); setLast(r); await q.reload(); return r; });
  return (
    <Panel title="Content sync" br="BR8">
      <div className="toolbar" style={{ margin: "0 0 10px" }}>
        <Select label="Content" value={contentId} options={lessons} onChange={setContentId} render={(l) => l.title} />
      </div>
      <textarea rows={5} value={body} onChange={(e) => setBody(e.target.value)} aria-label="New content body" />
      <div className="actions" style={{ marginTop: 8 }}>
        <Btn primary onClick={() => void publish.run()} pending={publish.pending} disabled={!contentId || !body.trim()}>Publish new version</Btn>
      </div>
      {publish.error && <div className="error">{publish.error}</div>}
      {last && (
        <>
          <div className="ok">Version {last.version} published, {last.notifications_created} learner{last.notifications_created === 1 ? "" : "s"} notified.</div>
          <ul className="steps">
            {last.sync.map((s) => (
              <li key={s.step}><Tag kind={s.status === "done" ? "ok" : undefined}>{s.status}</Tag><span>{s.step}</span><span className="ms">{s.ms} ms</span></li>
            ))}
          </ul>
        </>
      )}
      <Status loading={q.loading && !q.data} error={q.error}>
        {q.data && (
          <dl className="kv small" style={{ marginTop: 12 }}>
            <dt>Title</dt><dd>{q.data.title}</dd>
            <dt>Type</dt><dd>{q.data.content_type}</dd>
            <dt>Versions</dt><dd>{q.data.versions.map((v) => `v${v.number} (${formatTime(v.published_at)})`).join(", ") || "none"}</dd>
            <dt>Indexed version</dt><dd>{q.data.indexed_version ?? "not indexed"}</dd>
            <dt>Chunks</dt><dd>{q.data.chunk_count}</dd>
            <dt>Cache</dt><dd><Tag kind={q.data.cache_state === "warm" ? "ok" : "warn"}>{q.data.cache_state}</Tag></dd>
            <dt>Search index</dt><dd>{q.data.search_version === null ? "not indexed" : `v${q.data.search_version}`}</dd>
          </dl>
        )}
      </Status>
    </Panel>
  );
}

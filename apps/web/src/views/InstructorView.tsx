import { useEffect, useMemo, useState } from "react";
import { analyticsApi, type VideoHeatmap } from "../analytics";
import { formatDay, pct, useAction, useFetch } from "../hooks";
import { Btn, Panel, Select, Status, Tag, ViewHead } from "../components/ui";
import { AnalyticsAccess, localDateTime, useAnalyticsPolling } from "../components/AnalyticsAccess";
import { AssessmentHealth } from "../components/AssessmentHealth";

export function InstructorView() {
  return (
    <>
      <ViewHead title="Instructor">
        Instructors spot questions and test cases that fail abnormally often, see where learners pause and rewind in a
        video, follow engagement over time, and trust that caches and search stay in sync when they change content.
      </ViewHead>
      <div className="grid">
        <div className="assessment-span"><AssessmentHealth /></div>
        <div className="assessment-span">
          <Panel title="Video heatmap, engagement and content sync" br="BR7 · BR8">
            <AnalyticsAccess role="instructor" source="lakehouse">
              {(token, session) => <LakehouseInsights token={token} courses={session.courses} />}
            </AnalyticsAccess>
          </Panel>
        </div>
      </div>
    </>
  );
}

function LakehouseInsights({ token, courses }: { token: string; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useState(courses[0]?.id ?? "");
  return (
    <>
      <p className="muted small">Built daily in the lakehouse from pseudonymised telemetry; each view shows when it was built.</p>
      <div className="toolbar">
        <Select label="Analytics course" value={course} options={courses} onChange={setCourse} render={(c) => c.title} />
      </div>
      {course && (
        <div className="stack">
          <Heatmap token={token} courseId={course} />
          <EngagementTrendView token={token} courseId={course} />
          <ContentSync token={token} courseId={course} />
        </div>
      )}
    </>
  );
}

type Second = VideoHeatmap["seconds"][number];

function Heatmap({ token, courseId }: { token: string; courseId: string }) {
  const client = analyticsApi(token);
  const videos = useFetch(() => client.courseVideos(courseId), [token, courseId]);
  const [contentId, setContentId] = useState("");
  const [version, setVersion] = useState("");
  useEffect(() => { setContentId(videos.data?.videos[0]?.content_id ?? ""); setVersion(""); }, [videos.data]);
  const [withLive, setWithLive] = useState(true);
  const q = useFetch(contentId ? () => client.heatmap(contentId, { version, live: String(withLive) }) : null, [token, contentId, version, withLive]);
  useAnalyticsPolling(q.reload);
  const [hover, setHover] = useState<number | null>(null);
  const step = q.data ? Math.max(1, Math.ceil(q.data.seconds.length / 240)) : 1;
  const merged = useMemo(() => {
    if (!q.data) return [];
    const live = new Map((q.data.live?.seconds ?? []).map((s) => [s.second, s]));
    return q.data.seconds.map((s) => {
      const l = live.get(s.second);
      return l ? { ...s, play: s.play + l.play, pause: s.pause + l.pause, seek: s.seek + l.seek, learners: Math.max(s.learners, l.learners) } : s;
    });
  }, [q.data]);
  const liveEvents = (q.data?.live?.seconds ?? []).reduce((a, s) => a + s.play + s.pause + s.seek, 0);
  const columns = useMemo(() => {
    if (!q.data) return [];
    const out: Second[] = [];
    for (let i = 0; i < merged.length; i += step) {
      const slice = merged.slice(i, i + step);
      out.push({
        second: slice[0].second,
        play: slice.reduce((a, b) => a + b.play, 0),
        pause: slice.reduce((a, b) => a + b.pause, 0),
        seek: slice.reduce((a, b) => a + b.seek, 0),
        learners: Math.max(...slice.map((b) => b.learners)),
        intensity: Math.max(...slice.map((b) => b.intensity)),
      });
    }
    return out;
  }, [q.data, merged, step]);
  // Scale to the 99th percentile: the first second (playback start) and the last (positions past
  // the end are clamped there) dwarf the rest; taller columns are clipped and marked, exact counts in the tooltip.
  const scale = useMemo(() => {
    const totals = columns.map((b) => b.play + b.pause + b.seek).sort((a, b) => a - b);
    return Math.max(1, totals[Math.floor((totals.length - 1) * 0.99)] ?? 1);
  }, [columns]);
  const height = (n: number) => `${Math.min(100, (n / scale) * 100)}%`;
  const h = hover !== null ? columns[hover] : null;
  const selected = videos.data?.videos.find((v) => v.content_id === contentId);
  return (
    <div>
      <h3 className="subhead">Video heatmap <span className="muted small">BR7</span></h3>
      <Status loading={videos.loading && !videos.data} error={videos.error} empty={videos.data && videos.data.videos.length === 0 ? "No heatmap has been built for this course's videos yet." : false}>
        <div className="toolbar" style={{ margin: "0 0 10px" }}>
          <Select label="Lesson video" value={contentId} options={(videos.data?.videos ?? []).map((v) => ({ ...v, id: v.content_id }))} onChange={(v) => { setContentId(v); setVersion(""); }} render={(v) => v.title ?? v.content_id} />
          <label className="field checkbox"><input type="checkbox" checked={withLive} onChange={(e) => setWithLive(e.target.checked)} /><span>Include today (live)</span></label>
          {selected && selected.versions.length > 1 && (
            <label className="field"><span>Video version</span>
              <select value={version} onChange={(e) => setVersion(e.target.value)}>
                <option value="">Newest</option>
                {selected.versions.map((v) => <option key={v.version ?? "none"} value={v.version ?? ""}>v{v.version} ({v.duration_sec ?? "?"} s)</option>)}
              </select>
            </label>
          )}
        </div>
        <Status loading={q.loading && !q.data} error={q.error}>
          {q.data && (
            <>
              <div className="muted small" style={{ marginBottom: 6 }}>
                {q.data.video.title}, version {q.data.video.version ?? "unknown"}, {q.data.video.duration_sec ?? q.data.seconds.length} s
                {step > 1 ? `, ${step} s per column` : ""}. Last {q.data.window_days} days to {formatDay(q.data.as_of)}, built {localDateTime(q.data.built_at)}.
                {q.data.live && q.data.live.days.length > 0 && <> <Tag kind="blue">live</Tag> plus {liveEvents} streamed interaction{liveEvents === 1 ? "" : "s"} from {q.data.live.days.map(formatDay).join(", ")}, updated {localDateTime(q.data.live.updated_at)}.</>}
                {withLive && q.data.live === null && q.data.versions[0]?.version !== q.data.video.version && <> Live events apply to the newest version only.</>}
              </div>
              <div className="heat" onMouseLeave={() => setHover(null)}>
                {h && <div className="tip" style={{ left: `${(hover! / columns.length) * 100}%` }}>{h.second}s: {h.play} play, {h.pause} pause, {h.seek} seek, {h.learners} learners</div>}
                {columns.map((b, i) => {
                  const total = b.play + b.pause + b.seek;
                  const clipped = total > scale;
                  const k = clipped ? scale / total : 1; // keep the play/pause/seek proportions when clipping
                  return (
                    <div className={clipped ? "col clipped" : "col"} key={b.second} onMouseEnter={() => setHover(i)} title={`${b.second}s`}>
                      {total === 0 ? <i style={{ height: 1, background: "var(--border)" }} /> : (
                        <>
                          <i className="play" style={{ height: height(b.play * k) }} />
                          <i className="pause" style={{ height: height(b.pause * k) }} />
                          <i className="seek" style={{ height: height(b.seek * k) }} />
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
                <span className="muted">Dense pause and seek columns mark confusing moments. A dark cap marks a column cut off by the scale.</span>
              </div>
            </>
          )}
        </Status>
      </Status>
    </div>
  );
}

function EngagementTrendView({ token, courseId }: { token: string; courseId: string }) {
  const [asOf, setAsOf] = useState("");
  const q = useFetch(() => analyticsApi(token).engagementTrend(courseId, { as_of: asOf }), [token, courseId, asOf]);
  useAnalyticsPolling(q.reload);
  const live = q.data?.live ?? null;
  const newToday = live ? Object.keys(live.scores).filter((p) => !q.data!.learners.some((l) => l.learner_pseudonym === p)).length : 0;
  const W = 320, H = 90, P = 6;
  const max = useMemo(() => Math.max(1, ...(q.data?.learners.flatMap((l) => l.scores) ?? []), ...(q.data?.course_avg ?? [])), [q.data]);
  const [showAll, setShowAll] = useState(false);
  const sorted = useMemo(() => [...(q.data?.learners ?? [])].sort((a, b) => Number(b.declining) - Number(a.declining)), [q.data]);
  const learners = showAll ? sorted : sorted.slice(0, 12);
  const path = (scores: number[]) => {
    const n = scores.length;
    if (n === 0) return "";
    return scores.map((s, i) => `${i === 0 ? "M" : "L"}${P + (i / Math.max(1, n - 1)) * (W - 2 * P)},${H - P - (s / max) * (H - 2 * P)}`).join(" ");
  };
  return (
    <div>
      <h3 className="subhead">Engagement trend <span className="muted small">BR8</span></h3>
      <div className="toolbar" style={{ margin: "0 0 10px" }}>
        <label className="field"><span>Trend as of (UTC)</span><input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
      </div>
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.learners.length === 0 ? "No learner activity in these weeks." : false}>
        {q.data && (
          <>
            <div className="muted small" style={{ marginBottom: 8 }}>
              {q.data.week_starts.length} weekly windows from {formatDay(q.data.week_starts[0])} to {formatDay(q.data.as_of)}, built {localDateTime(q.data.built_at)}.{" "}
              <strong>{q.data.declining_count} declining</strong> (score down at least {pct(q.data.decline_ratio)} in each of the last two weeks). Learners are shown by pseudonym.
            </div>
            {live && (
              <div className="small" style={{ marginBottom: 8 }} aria-live="polite">
                <Tag kind="blue">live</Tag> Today ({formatDay(live.day)}) so far: {Object.keys(live.scores).length} active learner{Object.keys(live.scores).length === 1 ? "" : "s"}, average {live.course_avg?.toFixed(1) ?? "–"} points{newToday ? `, ${newToday} not yet in the weekly trend` : ""}. Updated {localDateTime(live.updated_at)}.
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10 }}>
              {learners.map((l) => (
                <div key={l.learner_pseudonym} className="item" style={{ padding: 8, borderColor: l.declining ? "var(--red)" : undefined }}>
                  <div className="small" style={{ display: "flex", justifyContent: "space-between" }}>
                    <span className="mono">{l.learner_pseudonym.slice(0, 10)}</span>
                    {l.declining && <Tag kind="bad">declining</Tag>}
                  </div>
                  <svg viewBox={`0 0 ${W} ${H}`} width="100%" height="70" role="img" aria-label={`Engagement of ${l.learner_pseudonym}`}>
                    <path d={path(q.data!.course_avg)} fill="none" stroke="var(--border-strong)" strokeWidth="2" strokeDasharray="4 3" />
                    <path d={path(l.scores)} fill="none" stroke={l.declining ? "var(--red)" : "var(--green)"} strokeWidth="2.5" />
                  </svg>
                  <div className="muted small num">latest week {l.scores[l.scores.length - 1]?.toFixed(1) ?? "–"}{live ? ` · today ${(live.scores[l.learner_pseudonym] ?? 0).toFixed(1)}` : ""}</div>
                </div>
              ))}
            </div>
            {sorted.length > 12 && (
              <div className="actions" style={{ marginTop: 8 }}>
                <Btn onClick={() => setShowAll(!showAll)}>{showAll ? "Show declining and first learners" : `Show all ${sorted.length} learners`}</Btn>
              </div>
            )}
            <div className="legend"><span><i style={{ background: "var(--border-strong)" }} />course average</span><span><i style={{ background: "var(--green)" }} />learner</span></div>
          </>
        )}
      </Status>
    </div>
  );
}

function ContentSync({ token, courseId }: { token: string; courseId: string }) {
  const client = analyticsApi(token);
  const list = useFetch(() => client.courseContent(courseId), [token, courseId]);
  useAnalyticsPolling(list.reload);
  const [picked, setPicked] = useState("");
  useEffect(() => setPicked(""), [courseId]);
  const contentId = picked || list.data?.items[0]?.content_id || "";
  const current = list.data?.items.find((i) => i.content_id === contentId);
  const doc = useFetch(contentId ? () => client.contentDocument(contentId) : null, [token, contentId]);
  const loaded = doc.data?.content_id === contentId ? doc.data : null; // never edit a stale document
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  useEffect(() => { if (loaded) { setTitle(loaded.title); setBody(loaded.body); } }, [loaded?.content_id, loaded?.version]); // eslint-disable-line react-hooks/exhaustive-deps
  const [pending, setPending] = useState<{ version: number; at: number } | null>(null);
  const [synced, setSynced] = useState<{ version: number; seconds: number } | null>(null);
  const publish = useAction(async () => {
    const r = await client.publishVersion(contentId, body, title);
    setSynced(null);
    if (r.changed) setPending({ version: r.version, at: Date.now() });
    await list.reload();
    return r;
  });
  // poll fast while a published version travels LMS -> CDC -> content-sync
  useEffect(() => {
    if (!pending) return;
    const id = window.setInterval(() => void list.reload(), 1000);
    return () => window.clearInterval(id);
  }, [pending, list.reload]);
  useEffect(() => {
    if (pending && current?.in_sync && current.indexed_version === pending.version) {
      setSynced({ version: pending.version, seconds: (Date.now() - pending.at) / 1000 });
      setPending(null);
      void doc.reload();
    }
  }, [pending, current]); // eslint-disable-line react-hooks/exhaustive-deps
  const [query, setQuery] = useState("left join");
  const [mode, setMode] = useState<"keyword" | "hybrid">("hybrid");
  const search = useAction(() => client.search(courseId, query, mode));
  return (
    <div>
      <h3 className="subhead">Content sync and search <span className="muted small">BR8</span></h3>
      <p className="muted small">
        Publishing saves a new immutable version in object storage and the LMS. Change data capture then drives the
        sync service: cache invalidated, transcript re-chunked and embedded, search index refreshed.
      </p>
      <Status loading={list.loading && !list.data} error={list.error} empty={list.data && list.data.items.length === 0 ? "No content in this course." : false}>
        <div className="analytics-table">
          <table>
            <thead><tr><th>Content</th><th className="num">LMS version</th><th className="num">Indexed</th><th className="num">Chunks</th><th>Cache</th><th>Search</th></tr></thead>
            <tbody>
              {list.data?.items.map((i) => (
                <tr key={i.content_id}>
                  <td><button className="btn" aria-pressed={i.content_id === contentId} onClick={() => setPicked(i.content_id)}>{i.title}</button></td>
                  <td className="num">v{i.version}</td>
                  <td className="num">{i.indexed_version === null ? "–" : `v${i.indexed_version}`}</td>
                  <td className="num">{i.chunk_count}</td>
                  <td><Tag kind={i.cache_state === "warm" ? "ok" : "warn"}>{i.cache_state}</Tag></td>
                  <td>{i.in_sync ? <Tag kind="ok">in sync</Tag> : <Tag kind="warn">syncing</Tag>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
      {contentId && (
        <div className="stack" style={{ marginTop: 12 }}>
          <div>
            <Status loading={!loaded && !doc.error} error={doc.error}>
              {loaded && (
                <>
                  <div className="muted small" style={{ marginBottom: 6 }}>Editing {loaded.title} from v{loaded.version} (served from cache: {loaded.cache}).</div>
                  <label className="field"><span>Title</span><input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} /></label>
                  <textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} aria-label="Transcript body" style={{ marginTop: 8 }} />
                  <div className="actions" style={{ marginTop: 8 }}>
                    <Btn primary onClick={() => void publish.run()} pending={publish.pending} disabled={!body.trim() || !!pending}>Publish new version</Btn>
                  </div>
                </>
              )}
            </Status>
            {publish.error && <div className="error">{publish.error}</div>}
            {publish.result && !publish.result.changed && <div className="muted small">No change: the title and body match the current version.</div>}
            {pending && <div className="muted small" aria-live="polite">Version {pending.version} saved. Waiting for change capture and the sync service…</div>}
            {synced && <div className="ok" aria-live="polite">Version {synced.version} is searchable {synced.seconds.toFixed(1)} s after publishing.</div>}
          </div>
          <div>
            <div className="toolbar" style={{ margin: 0 }}>
              <label className="field"><span>Search this course</span><input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && query.trim()) void search.run(); }} /></label>
              <label className="field"><span>Ranking</span>
                <select value={mode} onChange={(e) => setMode(e.target.value as "keyword" | "hybrid")}>
                  <option value="hybrid">Hybrid (keyword + vector)</option>
                  <option value="keyword">Keyword only</option>
                </select>
              </label>
              <Btn onClick={() => void search.run()} pending={search.pending} disabled={!query.trim()}>Search</Btn>
            </div>
            {search.error && <div className="error">{search.error}</div>}
            {search.result && (search.result.hits.length === 0 ? <p className="empty">No matching passages in the current versions.</p> : (
              <ul className="steps" aria-label="Search results">
                {search.result.hits.map((h) => (
                  <li key={`${h.content_id}-${h.ordinal}`}>
                    <span><strong>{h.title}</strong> <span className="muted small">v{h.version}{h.section_path.length ? ` · ${h.section_path.join(" › ")}` : ""}</span><br /><span className="small">{h.snippet}</span></span>
                  </li>
                ))}
              </ul>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

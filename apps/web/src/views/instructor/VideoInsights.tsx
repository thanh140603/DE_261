import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { Link } from "react-router-dom";
import { analyticsApi, type VideoHeatmap } from "../../analytics";
import { AnalyticsAccess, localDateTime, useAnalyticsPolling } from "../../components/AnalyticsAccess";
import { TipRow, useTip, useWidth } from "../../components/charts";
import { Icon } from "../../components/Icon";
import { Badge, Card, Chip, DataTable, PageHead, SelectField, Status, Switch, Tile } from "../../components/ui";
import { fmtNum, formatDay, useFetch } from "../../hooks";
import { CourseSelect, useInstructorCourse } from "./common";

interface Col { second: number; span: number; play: number; pause: number; seek: number; learners: number }
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const p99 = (a: number[]) => { const s = [...a].sort((x, y) => x - y); return Math.max(1, s[Math.floor((s.length - 1) * 0.99)] ?? 1); };

export function VideoInsights() {
  return (
    <>
      <PageHead br="BR7" title="Video insights">
        Where learners play, pause and seek in each lesson video. Built per video version in the lakehouse from pseudonymised viewing events; today's activity streams in live.
      </PageHead>
      <AnalyticsAccess role="instructor" source="lakehouse">{(token, session) => <Insights token={token} courses={session.courses} />}</AnalyticsAccess>
    </>
  );
}

function Insights({ token, courses }: { token: string; courses: { id: string; title: string }[] }) {
  const [course, setCourse] = useInstructorCourse(courses);
  const client = analyticsApi(token);
  const videos = useFetch(course ? () => client.courseVideos(course) : null, [token, course]);
  const [contentId, setContentId] = useState("");
  const [version, setVersion] = useState("");
  const [withLive, setWithLive] = useState(true);
  useEffect(() => { setContentId(videos.data?.videos[0]?.content_id ?? ""); setVersion(""); }, [videos.data]);
  const q = useFetch(contentId ? () => client.heatmap(contentId, { version, live: String(withLive) }) : null, [token, contentId, version, withLive]);
  useAnalyticsPolling(q.reload);
  const selected = videos.data?.videos.find((v) => v.content_id === contentId);

  const merged = useMemo(() => {
    if (!q.data) return [];
    const live = new Map((q.data.live?.seconds ?? []).map((s) => [s.second, s]));
    return q.data.seconds.map((s) => {
      const l = live.get(s.second);
      return l ? { ...s, play: s.play + l.play, pause: s.pause + l.pause, seek: s.seek + l.seek, learners: Math.max(s.learners, l.learners) } : s;
    });
  }, [q.data]);
  const sum = (k: "play" | "pause" | "seek") => merged.reduce((a, s) => a + s[k], 0);

  return (
    <>
      <div className="filters">
        <CourseSelect courses={courses} value={course} onChange={setCourse} />
        <SelectField label="Lesson video" value={contentId} options={videos.data?.videos ?? []} onChange={(v) => { setContentId(v); setVersion(""); }} render={(v) => v.title ?? v.content_id} valueOf={(v) => v.content_id} />
        {selected && selected.versions.length > 1 && (
          <label className="field">Video version
            <select className="select" value={version} onChange={(e) => setVersion(e.target.value)} aria-label="Video version">
              <option value="">Newest</option>
              {selected.versions.map((v) => <option key={v.version ?? "none"} value={v.version ?? ""}>Version {v.version} ({v.duration_sec ?? "?"} s)</option>)}
            </select>
          </label>
        )}
        <Switch label="Include today (live)" checked={withLive} onChange={setWithLive} />
      </div>
      <Status loading={videos.loading && !videos.data} error={videos.error} empty={videos.data && videos.data.videos.length === 0 ? "No heatmap has been built for this course's videos yet." : false}>
        <div className="tiles">
          <Tile label="Learners" value={q.data ? fmtNum(Math.max(0, ...merged.map((s) => s.learners))) : "–"} delta="most active at any one second" />
          <Tile label="Plays" value={q.data ? fmtNum(sum("play")) : "–"} delta={q.data ? `last ${q.data.window_days} days` : undefined} />
          <Tile label="Pauses" value={q.data ? fmtNum(sum("pause")) : "–"} delta={q.data?.live?.days.length ? "including today" : undefined} />
          <Tile label="Seeks" value={q.data ? fmtNum(sum("seek")) : "–"} delta="jumps back or ahead" />
        </div>
        <Status loading={q.loading && !q.data} error={q.error}>
          {q.data && <Body data={q.data} merged={merged} withLive={withLive} />}
        </Status>
      </Status>
    </>
  );
}

function Body({ data, merged, withLive }: { data: VideoHeatmap; merged: VideoHeatmap["seconds"]; withLive: boolean }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(320, width || 700);
  const padL = 84, padR = 10;
  const iw = W - padL - padR;
  const n = merged.length;
  const step = Math.max(1, Math.ceil(n / Math.max(40, Math.min(180, Math.floor(iw / 6)))));
  const cols = useMemo(() => {
    const out: Col[] = [];
    for (let i = 0; i < n; i += step) {
      const slice = merged.slice(i, i + step);
      out.push({
        second: slice[0].second, span: slice.length,
        play: slice.reduce((a, b) => a + b.play, 0), pause: slice.reduce((a, b) => a + b.pause, 0),
        seek: slice.reduce((a, b) => a + b.seek, 0), learners: Math.max(...slice.map((b) => b.learners)),
      });
    }
    return out;
  }, [merged, n, step]);

  // moments: columns whose pause+seek stands far above the median (ignoring the first/last columns,
  // where playback starts and positions past the end are clamped)
  const moments = useMemo(() => {
    const inner = cols.slice(1, -1).map((c, i) => ({ i: i + 1, score: c.pause + c.seek }));
    const sorted = inner.map((x) => x.score).sort((a, b) => a - b);
    const median = Math.max(1, sorted[Math.floor(sorted.length / 2)] ?? 1);
    const picked: { i: number; score: number; ratio: number }[] = [];
    for (const c of [...inner].sort((a, b) => b.score - a.score)) {
      if (picked.length === 3 || c.score < median * 1.5) break;
      if (picked.some((p) => Math.abs(p.i - c.i) <= 2)) continue;
      picked.push({ ...c, ratio: c.score / median });
    }
    return picked.sort((a, b) => a.i - b.i).map((p, k) => ({ ...p, pin: String.fromCharCode(65 + k) }));
  }, [cols]);

  const liveEvents = (data.live?.seconds ?? []).reduce((a, s) => a + s.play + s.pause + s.seek, 0);
  const segments = useMemo(() => {
    const rows: (string | number)[][] = [];
    const per = Math.max(1, Math.round(30 / step));
    for (let i = 0; i < cols.length; i += per) {
      const g = cols.slice(i, i + per);
      rows.push([`${mmss(g[0].second)}–${mmss(g[g.length - 1].second + g[g.length - 1].span)}`, Math.max(...g.map((c) => c.learners)), g.reduce((a, c) => a + c.play, 0), g.reduce((a, c) => a + c.pause, 0), g.reduce((a, c) => a + c.seek, 0)]);
    }
    return rows;
  }, [cols, step]);

  return (
    <div className="grid-2-1">
      <Card title={data.video.title ?? data.video.content_id}
        sub={<>{data.video.title}, version {data.video.version ?? "unknown"}, {data.video.duration_sec ?? n} s{step > 1 ? `, ${step} s per column` : ""}. Last {data.window_days} days to {formatDay(data.as_of)}, built {localDateTime(data.built_at)}.</>}
        actions={data.live && data.live.days.length > 0 ? <Badge tone="info" icon="activity">Live</Badge> : undefined}>
        {data.live && data.live.days.length > 0 && (
          <p className="small" style={{ marginBottom: 10 }} aria-live="polite">Plus {liveEvents} streamed interaction{liveEvents === 1 ? "" : "s"} from {data.live.days.map(formatDay).join(", ")}, updated {localDateTime(data.live.updated_at)}.</p>
        )}
        {withLive && data.live === null && data.versions[0]?.version !== data.video.version && <p className="small muted" style={{ marginBottom: 10 }}>Live events apply to the newest version only.</p>}
        <div className="legend" style={{ marginBottom: 10 }}>
          <span className="key"><span className="sw-line" style={{ background: "var(--s1)" }} />Active learners</span>
          <span className="key">Fewer <span className="ramp">{[1, 2, 3, 4, 5, 6].map((l) => <i key={l} style={{ background: `var(--h${l})` }} />)}</span> More events</span>
          {moments.length > 0 && <span className="key"><span className="pin-badge" style={{ width: 16, height: 16, fontSize: 10 }}>A</span>Moment to review</span>}
        </div>
        <div ref={ref}>
          <HeatChart cols={cols} moments={moments} width={W} padL={padL} padR={padR} duration={data.video.duration_sec ?? n} />
        </div>
        <DataTable head={["Segment", "Active learners (peak)", "Plays", "Pauses", "Seeks"]} rows={segments} />
      </Card>
      <Card title="Moments to review" sub="Where pauses and seeks stand furthest above the rest of the video.">
        {moments.length === 0 && <p className="empty">No moment stands out: pauses and seeks are spread evenly across this video.</p>}
        {moments.map((m) => {
          const c = cols[m.i];
          return (
            <div className="moment" key={m.pin}>
              <span className="pin-badge">{m.pin}</span>
              <div>
                <div className="strong">{mmss(c.second)}–{mmss(c.second + c.span)}</div>
                <div className="chips" style={{ marginTop: 6 }}>
                  <Chip>{c.pause} pauses</Chip><Chip>{c.seek} seeks</Chip><Chip>{m.ratio.toFixed(1)}× the typical moment</Chip>
                </div>
                <p className="xs muted" style={{ marginTop: 6 }}>{c.learners} active learner{c.learners === 1 ? "" : "s"} at this point.</p>
              </div>
            </div>
          );
        })}
        <div className="card-foot"><Icon name="file" /><span>Clarify a confusing explanation in <Link to="/instructor/content">Content &amp; search</Link>. A new version starts its own heatmap.</span></div>
      </Card>
    </div>
  );
}

function HeatChart({ cols, moments, width: W, padL, padR, duration }: {
  cols: Col[]; moments: { i: number; pin: string }[]; width: number; padL: number; padR: number; duration: number;
}) {
  const t = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const [hostRef, setHost] = useState<HTMLDivElement | null>(null);
  const top = 28, viewH = 110, gap = 16, rowH = 22, rowGap = 6, axisH = 22;
  const rowsY = top + viewH + gap, H = rowsY + 3 * rowH + 2 * rowGap + axisH;
  const iw = W - padL - padR, N = Math.max(1, cols.length), cw = iw / N, cg = cw > 7 ? 2 : 1;
  const X = (i: number) => padL + i * cw;
  // playback start and positions past the end dwarf the rest: scale to the inner columns, clip the edges
  const inner = cols.length > 4 ? cols.slice(1, -1) : cols;
  const vMax = Math.max(1, ...inner.map((c) => c.learners));
  const VY = (v: number) => top + viewH - (Math.min(v, vMax) / vMax) * viewH;
  const rows: [string, "play" | "pause" | "seek"][] = [["Plays", "play"], ["Pauses", "pause"], ["Seeks", "seek"]];
  const scales = Object.fromEntries(rows.map(([, k]) => [k, p99(cols.map((c) => c[k]))])) as Record<string, number>;
  const d = cols.map((c, i) => `${i ? "L" : "M"}${(X(i) + cw / 2).toFixed(1)},${VY(c.learners).toFixed(1)}`).join("");
  const tickStep = duration > 900 ? 300 : duration > 300 ? (iw < 420 ? 120 : 60) : 30;
  const ticks: number[] = [];
  for (let s = 0; s <= duration; s += tickStep) ticks.push(s);
  const xOfSecond = (s: number) => padL + (Math.min(s, duration) / Math.max(1, duration)) * iw;

  function move(e: MouseEvent<SVGRectElement>) {
    const b = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const i = Math.max(0, Math.min(N - 1, Math.floor((((e.clientX - b.left) * W) / b.width - padL) / cw)));
    const c = cols[i];
    setHover(i);
    t.show(e, hostRef, <>
      <div className="tt-title">{mmss(c.second)}–{mmss(c.second + c.span)}</div>
      <TipRow color="var(--s1)" line label="Active learners" value={c.learners} />
      <TipRow label="Plays" value={c.play} /><TipRow label="Pauses" value={c.pause} /><TipRow label="Seeks" value={c.seek} />
    </>);
  }
  return (
    <div className="chart-host heat" ref={setHost}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="Video interaction heatmap: active learners, plays, pauses and seeks along the video">
        {moments.map((m) => {
          const x1 = X(m.i), x2 = X(m.i + 1), cx = (x1 + x2) / 2;
          return (
            <g key={m.pin}>
              <rect className="band" x={x1} y={top} width={x2 - x1} height={H - axisH - top} />
              <circle className="pin" cx={cx} cy={top - 14} r={9} />
              <text className="pin-text" x={cx} y={top - 14} dy="0.35em" textAnchor="middle">{m.pin}</text>
            </g>
          );
        })}
        {[0, vMax].map((v) => (
          <g key={v}>
            {v > 0 && <line className="gridline" x1={padL} x2={W - padR} y1={VY(v)} y2={VY(v)} />}
            <text className="tick" x={padL - 8} y={VY(v)} dy="0.32em" textAnchor="end">{v}</text>
          </g>
        ))}
        <line className="axis" x1={padL} x2={W - padR} y1={VY(0)} y2={VY(0)} />
        <path d={`${d}L${X(N - 1) + cw / 2},${VY(0)}L${X(0) + cw / 2},${VY(0)}Z`} fill="var(--s1-wash)" />
        <path d={d} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" />
        {rows.map(([label, k], r) => {
          const y = rowsY + r * (rowH + rowGap);
          return (
            <g key={k}>
              <text className="row-label" x={padL - 8} y={y + rowH / 2} dy="0.32em" textAnchor="end">{label}</text>
              {cols.map((c, i) => {
                const v = c[k], lvl = v <= 0 ? 0 : Math.max(1, Math.ceil(Math.min(1, v / scales[k]) * 6));
                return <rect key={i} className="col" x={X(i) + cg / 2} y={y} width={Math.max(1, cw - cg)} height={rowH} rx={2} fill={`var(--h${lvl})`} />;
              })}
            </g>
          );
        })}
        {ticks.map((s, i) => (
          <text key={s} className="tick" x={xOfSecond(s)} y={H - 6} textAnchor={i === 0 ? "start" : s >= duration ? "end" : "middle"}>{mmss(s)}</text>
        ))}
        {hover !== null && (
          <g>
            <line className="crosshair" x1={X(hover) + cw / 2} x2={X(hover) + cw / 2} y1={top} y2={H - axisH} />
            <circle cx={X(hover) + cw / 2} cy={VY(cols[hover].learners)} r={5} fill="var(--s1)" stroke="var(--chart-surface)" strokeWidth={2} />
          </g>
        )}
        <rect x={padL} y={0} width={iw} height={H - axisH} fill="transparent" onMouseMove={move} onMouseLeave={() => { setHover(null); t.hide(); }} />
      </svg>
      {t.node}
    </div>
  );
}

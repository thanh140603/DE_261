import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { LineChart, TipRow } from "../components/charts";
import { Icon } from "../components/Icon";
import { Badge, Btn, Callout, Card, DataTable, PageHead, Status, Tile } from "../components/ui";
import { fmtNum, formatTime, relTime, useAction, useFetch } from "../hooks";
import { useStore } from "../store";
import type { Stats, TelemetryInput, TopicMessage } from "../types";

// throughput samples survive navigation within the tab
const samples: { t: number; bronze: number }[] = [];
function record(stats: Stats | null) {
  if (!stats) return;
  const last = samples[samples.length - 1];
  if (last && Date.now() - last.t < 2000) { last.bronze = Math.max(last.bronze, stats.bronze); return; }
  samples.push({ t: Date.now(), bronze: stats.bronze });
  if (samples.length > 120) samples.shift();
}

export function PipelineView() {
  const { stats, refreshStats, lastEventAt } = useStore();
  const [, setTick] = useState(0);
  useEffect(() => { record(stats); setTick((t) => t + 1); }, [stats]);
  useEffect(() => { const id = window.setInterval(() => void refreshStats(), 5000); return () => window.clearInterval(id); }, [refreshStats]);
  const share = (n: number | undefined) => (stats && stats.bronze ? `${((100 * (n ?? 0)) / stats.bronze).toFixed(1)}% of received` : "–");
  return (
    <>
      <PageHead title="Pipeline health" actions={<Btn icon="refresh" onClick={() => void refreshStats()}>Refresh</Btn>}>
        Events enter as raw telemetry, are validated, migrated to the current schema and pseudonymised into silver, or land in the dead-letter queue with a reason. Every other page is derived from here.
      </PageHead>
      <div className="tiles">
        <Tile label="Events received" value={fmtNum(stats?.bronze)} delta={stats?.last_event_at ? `last one ${relTime(stats.last_event_at)}` : "bronze, as received"} />
        <Tile label="Accepted to silver" value={fmtNum(stats?.silver)} delta={share(stats?.silver)} />
        <Tile label="Rejected to dead letters" value={fmtNum(stats?.dlq)} delta={share(stats?.dlq)} />
        <Tile label="Late events accepted" value={fmtNum(stats?.late_events)} delta="placed by event time, not arrival" />
      </div>
      <Flow stats={stats} />
      <div className="grid-1-1 mt">
        <Throughput />
        <Simulator />
      </div>
      <div className="grid-1-1 mt">
        <Topics tick={lastEventAt} />
        <Dlq tick={lastEventAt} />
      </div>
      <div className="mt"><Silver tick={lastEventAt} /></div>
      <div className="mt"><SendOne /></div>
    </>
  );
}

function Node({ label, value, sub, warn }: { label: string; value: number | undefined; sub?: string; warn?: boolean }) {
  const prev = useRef(value);
  const [bump, setBump] = useState(false);
  useEffect(() => {
    if (prev.current !== undefined && value !== undefined && value !== prev.current) {
      setBump(true);
      const t = window.setTimeout(() => setBump(false), 600);
      prev.current = value;
      return () => window.clearTimeout(t);
    }
    prev.current = value;
  }, [value]);
  return (
    <div className={`node${bump ? " bump" : ""}`}>
      <div className="node-top"><i className={`dot ${value === undefined ? "idle" : warn ? "warn" : "ok"}`} /><span>{label}</span></div>
      <b>{fmtNum(value)}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

function Flow({ stats }: { stats: Stats | null }) {
  const topics = stats ? Object.values(stats.topics).reduce((a, b) => a + b, 0) : undefined;
  return (
    <Card title="Data flow" sub="Each box counts what passed through it. Personal identifiers are pseudonymised before the silver layer.">
      <div className="flow" aria-label="Pipeline flow">
        <div className="flow-col"><h4>Ingest</h4>
          <Node label="Event bus messages" value={topics} sub={stats ? `${Object.keys(stats.topics).length} topics: telemetry, CDC, LMS, sandbox` : undefined} />
        </div>
        <div className="flow-col"><h4>Bronze</h4>
          <Node label="Raw events" value={stats?.bronze} sub="stored as received" />
        </div>
        <div className="flow-col"><h4>Silver</h4>
          <Node label="Cleaned events" value={stats?.silver} sub="validated, pseudonymised" />
          <Node label="Dead letters" value={stats?.dlq} sub="rejected with a reason" warn={!!stats && stats.dlq > 0} />
        </div>
        <div className="flow-col"><h4>Outputs</h4>
          <Node label="Feature rows" value={stats?.feature_rows} sub="learner features" />
          <Node label="Graded submissions" value={stats?.submissions_graded} sub="BR3 feedback" />
          <Node label="Notifications sent" value={stats?.notifications_sent} sub={stats ? `${stats.notifications_suppressed} suppressed · BR1` : undefined} />
          <Node label="Demo risk alerts" value={stats?.risk_alerts} sub="in-process BR5 demo" warn={!!stats && stats.risk_alerts > 0} />
          <Node label="Content versions" value={stats?.content_versions} sub="BR8 sync" />
        </div>
      </div>
    </Card>
  );
}

function Throughput() {
  const rates = samples.slice(1).map((s, i) => ({ t: s.t, perMin: Math.max(0, ((s.bronze - samples[i].bronze) * 60000) / Math.max(1, s.t - samples[i].t)) }));
  const max = Math.max(10, ...rates.map((r) => r.perMin));
  const nice = Math.pow(10, Math.floor(Math.log10(max)));
  const yMax = Math.ceil(max / nice) * nice;
  const label = (t: number) => { const s = Math.round((Date.now() - t) / 1000); return s < 5 ? "now" : s < 60 ? `−${s} s` : `−${Math.round(s / 60)} min`; };
  return (
    <Card title="Events received per minute" sub="Sampled from the live counters since you opened this page.">
      {rates.length < 2
        ? <p className="empty">Collecting samples… Start the simulator to see throughput.</p>
        : (
          <>
            <LineChart x={rates.map((r) => label(r.t))} yMax={yMax} yTicks={[0, yMax / 2, yMax]} yFmt={(v) => fmtNum(Math.round(v))} height={210} endLabel
              label={`Events received per minute, latest ${Math.round(rates[rates.length - 1].perMin)}`}
              series={[{ name: "Events per minute", values: rates.map((r) => r.perMin), color: "var(--s1)", wash: true }]}
              tip={(i) => <><div className="tt-title">{formatTime(new Date(rates[i].t).toISOString())}</div><TipRow color="var(--s1)" line label="Events per minute" value={fmtNum(Math.round(rates[i].perMin))} /></>} />
            <DataTable head={["Time", "Events per minute"]} rows={rates.map((r) => [formatTime(new Date(r.t).toISOString()), fmtNum(Math.round(r.perMin))])} />
          </>
        )}
    </Card>
  );
}

function Simulator() {
  const status = useFetch(() => api.simulate.status(), []);
  const [rate, setRate] = useState(5);
  const [count, setCount] = useState(100);
  const start = useAction(async () => { const r = await api.simulate.start(rate); await status.reload(); return r; });
  const stop = useAction(async () => { const r = await api.simulate.stop(); await status.reload(); return r; });
  const burst = useAction(async () => { const r = await api.simulate.burst(count); await status.reload(); return r; });
  const late = useAction(() => api.simulate.scenario("late_mobile_events"));
  useEffect(() => {
    if (!status.data?.running) return;
    const t = window.setInterval(() => void status.reload(), 2000);
    return () => window.clearInterval(t);
  }, [status.data?.running, status.reload]);
  const err = start.error ?? stop.error ?? burst.error ?? late.error;
  const running = !!status.data?.running;
  return (
    <Card title={<><Icon name="zap" />Simulator</>} sub="Demo control: generates clickstream telemetry for the pipeline."
      actions={running ? <Badge tone="good" icon="activity">Running</Badge> : <Badge tone="neutral">Stopped</Badge>}>
      <Status loading={status.loading && !status.data} error={status.error}>
        <p className="small muted">{running ? `${status.data!.rate_per_sec} events per second` : "Not generating"} · {fmtNum(status.data?.generated)} events generated so far.</p>
      </Status>
      <div className="filters" style={{ marginTop: 12, marginBottom: 0 }}>
        <label className="field">Events per second<input className="input" style={{ width: 120 }} type="number" min={1} max={200} value={rate} onChange={(e) => setRate(Number(e.target.value))} /></label>
        {running
          ? <Btn variant="danger" icon="stop" onClick={() => void stop.run()} pending={stop.pending}>Stop simulator</Btn>
          : <Btn variant="primary" icon="play" onClick={() => void start.run()} pending={start.pending}>Start simulator</Btn>}
      </div>
      <div className="filters" style={{ marginTop: 12, marginBottom: 0 }}>
        <label className="field">Burst size<input className="input" style={{ width: 120 }} type="number" min={1} max={5000} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>
        <Btn onClick={() => void burst.run()} pending={burst.pending}>Send burst</Btn>
        <Btn onClick={() => void late.run()} pending={late.pending}>Scenario: late mobile events</Btn>
      </div>
      {err && <div className="mt"><Callout tone="bad">{err}</Callout></div>}
      {burst.result && <div className="mt"><Callout tone="good">Burst done: {burst.result.generated} generated, {burst.result.silver} to silver, {burst.result.dlq} rejected.</Callout></div>}
      {late.result && <ol className="small" style={{ paddingLeft: 18, marginBottom: 0 }}>{late.result.steps.map((s, i) => <li key={i}>{s.message}</li>)}</ol>}
    </Card>
  );
}

function Topics({ tick }: { tick: number }) {
  const q = useFetch(() => api.pipeline.topics(), []);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  const [open, setOpen] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<TopicMessage[]>([]);
  const [msgErr, setMsgErr] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    api.pipeline.topic(open, 10).then((m) => { setMsgs(m); setMsgErr(null); }).catch((e: Error) => setMsgErr(e.message));
  }, [open, tick]);
  return (
    <Card title="Event bus topics" sub="Kafka in production. Select a topic to see its latest messages.">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "No messages yet." : false}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Topic</th><th className="r">Messages</th><th className="r">Last</th></tr></thead>
            <tbody>
              {q.data?.map((t) => (
                <tr key={t.topic} aria-selected={open === t.topic}>
                  <td><button className="btn link mono" style={{ fontWeight: 600 }} onClick={() => setOpen(open === t.topic ? null : t.topic)} aria-expanded={open === t.topic}>{t.topic}</button></td>
                  <td className="r num">{fmtNum(t.count)}</td>
                  <td className="r num small muted nowrap">{relTime(t.last_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {open && (
          <div className="mt">
            <h3 className="section-title" style={{ marginTop: 0 }}>Latest on <span className="mono">{open}</span></h3>
            {msgErr && <Callout tone="bad">{msgErr}</Callout>}
            {msgs.map((m, i) => (
              <details key={`${m.key}-${i}`} style={{ padding: "4px 0" }}>
                <summary className="small"><span className="muted num">{formatTime(m.at)}</span> {m.event_type} <span className="muted">key {m.key}</span></summary>
                <pre className="block">{JSON.stringify(m.payload, null, 2)}</pre>
              </details>
            ))}
          </div>
        )}
      </Status>
    </Card>
  );
}

function Dlq({ tick }: { tick: number }) {
  const q = useFetch(() => api.pipeline.dlq(20), []);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card title="Dead-letter queue" sub="Latest rejected events and why.">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "Nothing rejected. Send a malformed event below to see one here." : false}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Time</th><th>Reason</th><th>Payload</th></tr></thead>
            <tbody>
              {q.data?.map((d) => (
                <tr key={d.event_id}>
                  <td className="num small nowrap">{formatTime(d.at)}</td>
                  <td className="small">{d.reason}</td>
                  <td><details><summary className="small muted mono">{d.event_id.slice(0, 8)}</summary><pre className="block">{JSON.stringify(d.payload, null, 2)}</pre></details></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
    </Card>
  );
}

function Silver({ tick }: { tick: number }) {
  const q = useFetch(() => api.pipeline.silver(30), []);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card title="Silver tail" sub="The newest normalised events. Learners appear only by pseudonym.">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "Silver is empty. Start the simulator or send an event." : false}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Occurred</th><th>Received</th><th>Learner (pseudonym)</th><th>Course</th><th>Verb</th><th>Platform</th><th className="r">Position</th><th>Schema</th><th className="r">Late by</th></tr></thead>
            <tbody>
              {q.data?.map((e) => (
                <tr key={e.event_id}>
                  <td className="num small nowrap">{formatTime(e.occurred_at)}</td>
                  <td className="num small nowrap">{formatTime(e.received_at)}</td>
                  <td className="mono">{e.learner_pseudonym.slice(0, 12)}</td>
                  <td className="small">{e.course_id}</td>
                  <td className="small">{e.verb}</td>
                  <td className="small">{e.platform}</td>
                  <td className="r num small">{e.video_position_sec ?? ""}</td>
                  <td className="small">{e.schema_version}</td>
                  <td className="r num small">{e.late ? <Badge tone="warn" icon="clock">{Math.round(e.lateness_seconds)} s</Badge> : `${Math.round(e.lateness_seconds)} s`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
    </Card>
  );
}

function SendOne() {
  const { overview } = useStore();
  const learners = overview?.learners ?? [];
  const [form, setForm] = useState<TelemetryInput>({ learner_id: "", verb: "viewed", platform: "android", late_seconds: 0, schema_version: "1.1", malformed: false });
  useEffect(() => { if (!form.learner_id && learners.length) setForm((f) => ({ ...f, learner_id: learners[0].id })); }, [learners, form.learner_id]);
  const send = useAction(() => api.simulate.telemetry({ ...form, course_id: learners.find((l) => l.id === form.learner_id)?.course_ids[0] }));
  const set = <K extends keyof TelemetryInput>(k: K, v: TelemetryInput[K]) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <details className="demo">
      <summary><Icon name="zap" />Demo controls · send one telemetry event</summary>
      <p className="small muted" style={{ marginBottom: 12 }}>Pick schema 1.0 to see the migration step, add lateness to see the late flag, or choose an unknown verb or a malformed payload to see a rejection.</p>
      <div className="filters">
        <label className="field">Learner<select className="select" value={form.learner_id} onChange={(e) => set("learner_id", e.target.value)}>{learners.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select></label>
        <label className="field">Verb<select className="select" value={form.verb} onChange={(e) => set("verb", e.target.value)}>
          {["logged_in", "viewed", "played", "paused", "seeked", "completed", "attempted", "submitted", "posted", "unknown_verb"].map((v) => <option key={v}>{v}</option>)}
        </select></label>
        <label className="field">Platform<select className="select" value={form.platform} onChange={(e) => set("platform", e.target.value)}>{["web", "android", "ios"].map((v) => <option key={v}>{v}</option>)}</select></label>
        <label className="field">Arrives late by (s)<input className="input" style={{ width: 120 }} type="number" min={0} value={form.late_seconds} onChange={(e) => set("late_seconds", Number(e.target.value))} /></label>
        <label className="field">Schema version<select className="select" value={form.schema_version} onChange={(e) => set("schema_version", e.target.value as "1.0" | "1.1")}><option>1.1</option><option>1.0</option></select></label>
        <label className="switch inline-toggle">Malformed payload<input type="checkbox" checked={!!form.malformed} onChange={(e) => set("malformed", e.target.checked)} /></label>
        <Btn variant="primary" onClick={() => void send.run()} pending={send.pending} disabled={!form.learner_id}>Send event</Btn>
      </div>
      {send.error && <Callout tone="bad">{send.error}</Callout>}
      {send.result && (
        <Callout tone={send.result.outcome === "silver" ? "good" : "warn"}>
          {send.result.outcome === "silver" ? "Accepted into silver" : `Rejected to the dead-letter queue: ${send.result.reason ?? "unknown reason"}`} (event {send.result.event_id.slice(0, 8)}).
        </Callout>
      )}
    </details>
  );
}

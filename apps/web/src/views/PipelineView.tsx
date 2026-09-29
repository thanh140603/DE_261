import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { formatTime, useAction, useFetch } from "../hooks";
import { Btn, Panel, Status, Tag, ViewHead } from "../components/ui";
import type { TelemetryInput, TopicMessage } from "../types";

export function PipelineView() {
  const { stats, lastEventAt, refreshStats } = useStore();
  return (
    <>
      <ViewHead title="Pipeline">
        Watch events enter as raw telemetry, get validated, migrated to the current schema and pseudonymised into
        silver, or land in the dead-letter queue with a reason. Everything the other views show is derived from here.
      </ViewHead>
      <div className="grid">
        <Simulator />
        <Panel title="Counters" br="medallion">
          {stats ? (
            <dl className="kv">
              <dt>Bronze (raw)</dt><dd>{stats.bronze}</dd>
              <dt>Silver (normalised)</dt><dd>{stats.silver}</dd>
              <dt>Dead letters</dt><dd>{stats.dlq}</dd>
              <dt>Late events</dt><dd>{stats.late_events}</dd>
              <dt>Feature rows</dt><dd>{stats.feature_rows}</dd>
              <dt>Risk alerts</dt><dd>{stats.risk_alerts}</dd>
              <dt>Submissions graded</dt><dd>{stats.submissions_graded}</dd>
              <dt>Notifications sent</dt><dd>{stats.notifications_sent}</dd>
              <dt>Notifications suppressed</dt><dd>{stats.notifications_suppressed}</dd>
              <dt>Content versions</dt><dd>{stats.content_versions}</dd>
              <dt>Last event</dt><dd>{formatTime(stats.last_event_at)}</dd>
            </dl>
          ) : <div className="empty">Waiting for the server.</div>}
          <div className="actions" style={{ marginTop: 10 }}><Btn onClick={() => void refreshStats()}>Refresh counters</Btn></div>
        </Panel>
        <SendOne />
        <Topics tick={lastEventAt} />
        <Dlq tick={lastEventAt} />
        <div style={{ gridColumn: "1 / -1" }}><Silver tick={lastEventAt} /></div>
      </div>
    </>
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
  return (
    <Panel title="Simulator" br="telemetry source">
      <Status loading={status.loading && !status.data} error={status.error}>
        <div className="muted small" style={{ marginBottom: 8 }}>
          {status.data?.running ? `Running at ${status.data.rate_per_sec} events per second` : "Stopped"}, {status.data?.generated ?? 0} events generated.
        </div>
      </Status>
      <div className="actions">
        <label className="field"><span>Events per second</span><input type="number" min={1} max={200} value={rate} onChange={(e) => setRate(Number(e.target.value))} /></label>
        {status.data?.running ? (
          <Btn danger onClick={() => void stop.run()} pending={stop.pending}>Stop simulator</Btn>
        ) : (
          <Btn primary onClick={() => void start.run()} pending={start.pending}>Start simulator</Btn>
        )}
      </div>
      <div className="actions">
        <label className="field"><span>Burst size</span><input type="number" min={1} max={5000} value={count} onChange={(e) => setCount(Number(e.target.value))} /></label>
        <Btn onClick={() => void burst.run()} pending={burst.pending}>Send burst</Btn>
        <Btn onClick={() => void late.run()} pending={late.pending}>Run scenario: late mobile events</Btn>
      </div>
      {err && <div className="error">{err}</div>}
      {burst.result && <div className="ok">Burst done: {burst.result.generated} generated, {burst.result.silver} to silver, {burst.result.dlq} rejected.</div>}
      {late.result && <ol className="small" style={{ paddingLeft: 18 }}>{late.result.steps.map((s, i) => <li key={i}>{s.message}</li>)}</ol>}
    </Panel>
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
    <Panel title="Send one event" br="validation, migration, lateness">
      <div className="actions">
        <label className="field"><span>Learner</span>
          <select value={form.learner_id} onChange={(e) => set("learner_id", e.target.value)}>{learners.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</select>
        </label>
        <label className="field"><span>Verb</span>
          <select value={form.verb} onChange={(e) => set("verb", e.target.value)}>
            {["logged_in", "viewed", "played", "paused", "seeked", "completed", "attempted", "submitted", "posted", "unknown_verb"].map((v) => <option key={v}>{v}</option>)}
          </select>
        </label>
        <label className="field"><span>Platform</span>
          <select value={form.platform} onChange={(e) => set("platform", e.target.value)}>{["web", "android", "ios"].map((v) => <option key={v}>{v}</option>)}</select>
        </label>
        <label className="field"><span>Arrives late by (s)</span><input type="number" min={0} value={form.late_seconds} onChange={(e) => set("late_seconds", Number(e.target.value))} /></label>
        <label className="field"><span>Schema version</span>
          <select value={form.schema_version} onChange={(e) => set("schema_version", e.target.value as "1.0" | "1.1")}><option>1.1</option><option>1.0</option></select>
        </label>
        <label className="check"><input type="checkbox" checked={!!form.malformed} onChange={(e) => set("malformed", e.target.checked)} /> malformed payload</label>
      </div>
      <div className="actions"><Btn primary onClick={() => void send.run()} pending={send.pending} disabled={!form.learner_id}>Send event</Btn></div>
      {send.error && <div className="error">{send.error}</div>}
      {send.result && (
        <div className={send.result.outcome === "silver" ? "ok" : "notice"}>
          {send.result.outcome === "silver" ? "Accepted into silver" : `Rejected to the dead-letter queue: ${send.result.reason ?? "unknown reason"}`} (event {send.result.event_id.slice(0, 8)}).
        </div>
      )}
      <p className="muted small">Pick schema 1.0 to see the migration step, add lateness to see the late flag, choose an unknown verb or malformed payload to see a rejection.</p>
    </Panel>
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
    api.pipeline.topic(open, 10).then(setMsgs).catch((e: Error) => setMsgErr(e.message));
  }, [open, tick]);
  return (
    <Panel title="Topics (event bus)" br="Kafka in production">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "No messages yet." : false}>
        <table>
          <thead><tr><th>Topic</th><th className="num">Messages</th><th>Last</th></tr></thead>
          <tbody>
            {q.data?.map((t) => (
              <tr key={t.topic}>
                <td><button className="btn" style={{ padding: "2px 8px" }} onClick={() => setOpen(open === t.topic ? null : t.topic)} aria-expanded={open === t.topic}>{t.topic}</button></td>
                <td className="num">{t.count}</td>
                <td className="num">{formatTime(t.last_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {open && (
          <div style={{ marginTop: 10 }}>
            <h3>Recent messages on {open}</h3>
            {msgErr && <div className="error">{msgErr}</div>}
            {msgs.map((m, i) => (
              <details key={`${m.key}-${i}`}>
                <summary className="small"><span className="muted num">{formatTime(m.at)}</span> {m.event_type} <span className="muted">key {m.key}</span></summary>
                <pre className="block">{JSON.stringify(m.payload, null, 2)}</pre>
              </details>
            ))}
          </div>
        )}
      </Status>
    </Panel>
  );
}

function Dlq({ tick }: { tick: number }) {
  const q = useFetch(() => api.pipeline.dlq(20), []);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel title="Dead-letter queue" br="rejected events">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "Nothing rejected. Send a malformed event to see one here." : false}>
        <table>
          <thead><tr><th>When</th><th>Reason</th><th>Payload</th></tr></thead>
          <tbody>
            {q.data?.map((d) => (
              <tr key={d.event_id}>
                <td className="num">{formatTime(d.at)}</td>
                <td><Tag kind="warn">{d.reason}</Tag></td>
                <td><details><summary className="small muted">{d.event_id.slice(0, 8)}</summary><pre className="block">{JSON.stringify(d.payload, null, 2)}</pre></details></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Status>
    </Panel>
  );
}

function Silver({ tick }: { tick: number }) {
  const q = useFetch(() => api.pipeline.silver(30), []);
  useEffect(() => { void q.reload(); }, [tick]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel title="Silver tail" br="normalised, pseudonymised">
      <Status loading={q.loading && !q.data} error={q.error} empty={q.data && q.data.length === 0 ? "Silver is empty. Start the simulator or send an event." : false}>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>Occurred</th><th>Received</th><th>Learner (pseudonym)</th><th>Course</th><th>Verb</th><th>Platform</th><th className="num">Position</th><th>Schema</th><th className="num">Late by</th></tr></thead>
            <tbody>
              {q.data?.map((e) => (
                <tr key={e.event_id}>
                  <td className="num">{formatTime(e.occurred_at)}</td>
                  <td className="num">{formatTime(e.received_at)}</td>
                  <td className="mono">{e.learner_pseudonym.slice(0, 12)}</td>
                  <td>{e.course_id}</td>
                  <td>{e.verb}</td>
                  <td>{e.platform}</td>
                  <td className="num">{e.video_position_sec ?? ""}</td>
                  <td>{e.schema_version}</td>
                  <td className="num">{e.late ? <Tag kind="warn">{Math.round(e.lateness_seconds)} s</Tag> : `${Math.round(e.lateness_seconds)} s`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Status>
    </Panel>
  );
}

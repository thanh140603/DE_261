import { useState } from "react";
import { useStore } from "../store";
import { formatTime } from "../hooks";

function summarise(type: string, p: Record<string, unknown>): string {
  const s = (k: string) => (p[k] === undefined || p[k] === null ? "" : String(p[k]));
  switch (type) {
    case "telemetry.raw":
    case "telemetry.silver":
      return `${s("verb") || "event"} ${s("learner_pseudonym") || s("learner_id")} ${s("course_id")}`.trim();
    case "telemetry.dlq":
      return `rejected: ${s("reason")}`;
    case "notification":
      return `${s("title")} (${s("learner_id")})`;
    case "risk.alert":
      return `${s("learner_id")} ${s("course_id")} score ${s("score")}`;
    case "submission.graded":
      return `${s("submission_id") || s("id")} pass rate ${s("pass_rate")}`;
    case "content.sync":
      return `${s("content_id")} v${s("version")} ${s("step") || ""}`.trim();
    default:
      return JSON.stringify(p).slice(0, 80);
  }
}

const cls = (type: string) =>
  type === "notification" ? "notif" : type.startsWith("risk") ? "risk" : type.endsWith("dlq") ? "dlq" : "";

export function EventDrawer() {
  const { events, connected } = useStore();
  const [open, setOpen] = useState(false);
  return (
    <div className="drawer">
      {open && (
        <div className="panel" style={{ marginBottom: 8 }}>
          <header>
            <h3>Live events</h3>
            <span className="br">{connected ? "streaming" : "reconnecting"}</span>
          </header>
          <div className="log">
            {events.length === 0 && <div className="empty" style={{ padding: "14px 12px" }}>Nothing yet. Start the simulator or use any control.</div>}
            {events.map((e, i) => (
              <div className="row" key={`${e.at}-${i}`}>
                <span className="muted num">{formatTime(e.at)}</span>
                <span className={`type ${cls(e.type)}`}>{e.type}</span>
                <span>{summarise(e.type, e.payload)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <button className="toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span>Live events</span>
        <span className="muted num">{events.length} recent, {open ? "hide" : "show"}</span>
      </button>
    </div>
  );
}

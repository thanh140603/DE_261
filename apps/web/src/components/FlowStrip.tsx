import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";

interface StageProps { label: string; value: number | undefined; sub?: string; kind?: "source" | "stage" | "out" | "warn" }

function Box({ label, value, sub, kind = "stage" }: StageProps) {
  const prev = useRef<number | undefined>(value);
  const [bump, setBump] = useState(false);
  useEffect(() => {
    if (prev.current !== undefined && value !== undefined && value !== prev.current) {
      setBump(true);
      const t = window.setTimeout(() => setBump(false), 500);
      prev.current = value;
      return () => window.clearTimeout(t);
    }
    prev.current = value;
  }, [value]);
  return (
    <div className={`box ${kind}${bump ? " bump" : ""}`}>
      <div className="label">{label}</div>
      <div className="value num">{value === undefined ? "–" : value.toLocaleString()}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

const Link = () => <span className="link" aria-hidden="true" />;

export function FlowStrip() {
  const { stats } = useStore();
  const topicsTotal = stats ? Object.values(stats.topics).reduce((a, b) => a + b, 0) : undefined;
  return (
    <div className="strip" aria-label="Pipeline flow">
      <div className="stage">
        <Box label="Sources (Kafka topics)" value={topicsTotal} sub="telemetry, CDC, LMS, sandbox" kind="source" />
        <Link />
      </div>
      <div className="stage">
        <Box label="Bronze (raw)" value={stats?.bronze} sub="as received" />
        <Link />
      </div>
      <div className="stage">
        <Box label="Silver (normalised)" value={stats?.silver} sub={stats ? `${stats.dlq} rejected, ${stats.late_events} late` : undefined} kind={stats && stats.dlq > 0 ? "warn" : "stage"} />
        <Link />
      </div>
      <div className="stage">
        <div className="fan">
          <Box label="Feature rows" value={stats?.feature_rows} kind="out" />
          <Box label="Risk alerts" value={stats?.risk_alerts} kind={stats && stats.risk_alerts > 0 ? "warn" : "out"} />
          <Box label="Graded" value={stats?.submissions_graded} kind="out" />
          <Box label="Notifications" value={stats?.notifications_sent} sub={stats ? `${stats.notifications_suppressed} suppressed` : undefined} kind="out" />
        </div>
      </div>
    </div>
  );
}

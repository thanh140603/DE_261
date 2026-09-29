import { useStore } from "../store";

export function TopBar() {
  const { connected } = useStore();
  return (
    <header className="topbar">
      <span className="brand">DE_261 learning data platform</span>
      <span className="muted small">demo</span>
      <span className={`live${connected ? " on" : ""}`} title={connected ? "Receiving live events" : "Reconnecting"}>
        <span className="dot" aria-hidden="true" />
        {connected ? "live" : "reconnecting"}
      </span>
    </header>
  );
}

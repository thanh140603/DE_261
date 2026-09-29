import type { ReactNode } from "react";

export function Panel({ title, br, children }: { title: string; br?: string; children: ReactNode }) {
  return (
    <section className="panel">
      <header>
        <h2>{title}</h2>
        {br && <span className="br">{br}</span>}
      </header>
      <div className="content">{children}</div>
    </section>
  );
}

export function ViewHead({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="view-head">
      <h1>{title}</h1>
      <p>{children}</p>
    </div>
  );
}

export function Status({ loading, error, empty, children }: { loading: boolean; error: string | null; empty?: string | false; children?: ReactNode }) {
  if (error) return <div className="error">Could not load: {error}</div>;
  if (loading) return <div className="empty">Loading…</div>;
  if (empty) return <div className="empty">{empty}</div>;
  return <>{children}</>;
}

export function Select<T extends { id: string }>({
  label, value, options, onChange, render,
}: { label: string; value: string; options: T[]; onChange: (id: string) => void; render: (o: T) => string }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{render(o)}</option>
        ))}
      </select>
    </label>
  );
}

export function Btn({ children, onClick, pending, primary, danger, disabled }: {
  children: ReactNode; onClick: () => void; pending?: boolean; primary?: boolean; danger?: boolean; disabled?: boolean;
}) {
  return (
    <button className={`btn${primary ? " primary" : ""}${danger ? " danger" : ""}`} onClick={onClick} disabled={disabled || pending}>
      {pending ? "Working…" : children}
    </button>
  );
}

export function Tag({ kind, children }: { kind?: "ok" | "warn" | "bad" | "blue"; children: ReactNode }) {
  return <span className={`tag${kind ? ` ${kind}` : ""}`}>{children}</span>;
}

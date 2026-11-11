import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

/* ---------- layout ---------- */

export function PageHead({ eyebrow, title, br, children, actions }: {
  eyebrow?: ReactNode; title: ReactNode; br?: string; children?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}{br && <Br>{br}</Br>}</h1>
        {children && <p className="lede">{children}</p>}
      </div>
      {actions && <div className="head-actions">{actions}</div>}
    </div>
  );
}

export function Card({ title, sub, br, actions, children, className, id, label, footer }: {
  title?: ReactNode; sub?: ReactNode; br?: string; actions?: ReactNode; children?: ReactNode;
  className?: string; id?: string; label?: string; footer?: ReactNode;
}) {
  return (
    <section className={`card${className ? ` ${className}` : ""}`} id={id} aria-label={label}>
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2 className="card-title">{title}{br && <Br>{br}</Br>}</h2>}
            {sub && <p className="card-sub">{sub}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
      {footer && <div className="card-foot"><Icon name="info" /><span>{footer}</span></div>}
    </section>
  );
}

export const Br = ({ children }: { children: ReactNode }) => <span className="br">{children}</span>;

export function Tile({ label, value, delta, wide }: { label: ReactNode; value: ReactNode; delta?: ReactNode; wide?: boolean }) {
  return (
    <div className={`tile${wide ? " wide" : ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {delta !== undefined && <div className="tile-delta">{delta}</div>}
    </div>
  );
}

/* ---------- status ---------- */

export type Tone = "good" | "warn" | "serious" | "crit" | "info" | "neutral";
const TONE_ICON: Record<Tone, string> = { good: "check", warn: "alert", serious: "alert", crit: "octagon", info: "info", neutral: "minus" };

export function Badge({ tone, icon, children }: { tone: Tone; icon?: string; children: ReactNode }) {
  return <span className={`badge b-${tone}`}><Icon name={icon ?? TONE_ICON[tone]} />{children}</span>;
}

export const Chip = ({ children }: { children: ReactNode }) => <span className="chip">{children}</span>;

export function Callout({ tone, icon, children }: { tone: "info" | "warn" | "good" | "bad" | "neutral"; icon?: string; children: ReactNode }) {
  const fallback = { info: "info", warn: "alert", good: "check", bad: "octagon", neutral: "info" }[tone];
  return <div className={`callout ${tone}`} role={tone === "bad" ? "alert" : undefined}><Icon name={icon ?? fallback} /><div>{children}</div></div>;
}

/** Loading / error / empty switch for one fetched resource. */
export function Status({ loading, error, empty, children }: { loading: boolean; error: string | null; empty?: string | false; children?: ReactNode }) {
  if (error) return <Callout tone="bad">Could not load: {error}</Callout>;
  if (loading) return <div className="loading"><span className="spinner" />Loading…</div>;
  if (empty) return <p className="empty">{empty}</p>;
  return <>{children}</>;
}

export function Meter({ value, label }: { value: number | null | undefined; label?: string }) {
  const v = value === null || value === undefined ? null : Math.max(0, Math.min(1, value));
  return (
    <div className="meter" aria-label={label}>
      <div className="meter-track"><div className="meter-fill" style={{ width: `${(v ?? 0) * 100}%` }} /></div>
      <span className="num">{v === null ? "–" : `${Math.round(v * 100)}%`}</span>
    </div>
  );
}

/* ---------- controls ---------- */

export function Btn({ children, onClick, pending, variant, size, disabled, type = "button", icon, label }: {
  children?: ReactNode; onClick?: () => void; pending?: boolean; variant?: "primary" | "ghost" | "danger" | "link";
  size?: "sm"; disabled?: boolean; type?: "button" | "submit"; icon?: string; label?: string;
}) {
  return (
    <button type={type} className={`btn${variant ? ` ${variant}` : ""}${size ? ` ${size}` : ""}`} onClick={onClick} disabled={disabled || pending} aria-label={label}>
      {pending ? <span className="spinner" /> : icon && <Icon name={icon} />}
      {children}
    </button>
  );
}

export function SelectField<T>({ label, value, options, onChange, render, valueOf, placeholder }: {
  label: string; value: string; options: T[]; onChange: (value: string) => void;
  render: (o: T) => string; valueOf: (o: T) => string; placeholder?: string;
}) {
  return (
    <label className="field">{label}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {placeholder !== undefined && <option value="">{placeholder}</option>}
        {options.map((o) => <option key={valueOf(o)} value={valueOf(o)}>{render(o)}</option>)}
      </select>
    </label>
  );
}

export function Seg<V extends string>({ label, ariaLabel, value, options, onChange }: {
  label: string; ariaLabel?: string; value: V; options: { value: V; label: string }[]; onChange: (v: V) => void;
}) {
  return (
    <div className="field">{label}
      <div className="seg" role="group" aria-label={ariaLabel ?? label}>
        {options.map((o) => <button type="button" key={o.value} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>{o.label}</button>)}
      </div>
    </div>
  );
}

export function Switch({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <label className="switch inline-toggle">{label}<input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} /></label>;
}

export function Pager({ offset, total, limit = 20, onChange }: { offset: number; total: number; limit?: number; onChange: (offset: number) => void }) {
  if (total <= limit && offset === 0) return null;
  return (
    <div className="pager" aria-label="Pagination">
      <span className="num">{total ? `${offset + 1}–${Math.min(offset + limit, total)} of ${total}` : "0 results"}</span>
      <Btn size="sm" onClick={() => onChange(Math.max(0, offset - limit))} disabled={offset === 0}>Previous</Btn>
      <Btn size="sm" onClick={() => onChange(offset + limit)} disabled={offset + limit >= total}>Next</Btn>
    </div>
  );
}

/** Accessible table fallback for a chart. */
export function DataTable({ head, rows, summary = "View as table" }: { head: string[]; rows: ReactNode[][]; summary?: string }) {
  return (
    <details className="data-table">
      <summary>{summary}</summary>
      <div className="table-wrap">
        <table className="t">
          <thead><tr>{head.map((h, i) => <th key={h} className={i ? "r" : undefined}>{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j ? "r num" : undefined}>{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}

/* ---------- toast ---------- */

const ToastContext = createContext<(message: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((m: string) => {
    setMessage(m);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), 2800);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      {message && <div className="toast" role="status"><Icon name="check" />{message}</div>}
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

import { useCallback, useEffect, useRef, useState } from "react";

export interface Fetched<D> {
  data: D | null;
  error: string | null;
  loading: boolean;
  reload: () => Promise<void>;
}

/** Fetches once and whenever `deps` change. `reload()` refetches silently (keeps stale data). */
export function useFetch<D>(fn: (() => Promise<D>) | null, deps: unknown[]): Fetched<D> {
  const [data, setData] = useState<D | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!fn);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const seq = useRef(0);

  const run = useCallback(async (silent: boolean) => {
    const f = fnRef.current;
    if (!f) {
      setData(null);
      setLoading(false);
      return;
    }
    const id = ++seq.current;
    if (!silent) setLoading(true);
    try {
      const d = await f();
      if (id === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (id === seq.current) setError((e as Error).message);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void run(false);
    return () => { seq.current += 1; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const reload = useCallback(() => run(true), [run]);
  return { data, error, loading, reload };
}

/** Wraps an action (button handler) with pending / error state. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<R | null>(null);
  const run = useCallback(
    async (...args: A) => {
      setPending(true);
      setError(null);
      try {
        const r = await fn(...args);
        setResult(r);
        return r;
      } catch (e) {
        setError((e as Error).message);
        return null;
      } finally {
        setPending(false);
      }
    },
    [fn],
  );
  return { run, pending, error, result };
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

/** A calendar day ("2026-10-17", warehouse dates are UTC days) without shifting it into the viewer's zone. */
export function formatDay(day: string | null | undefined): string {
  if (!day) return "–";
  const d = new Date(`${day.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return day;
  return d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "–" : `${(v * 100).toFixed(digits)}%`;

/** State that survives navigation and reloads within the browser tab. */
export function usePersisted(key: string, initial: string): [string, (v: string) => void] {
  const [value, setValue] = useState<string>(() => {
    try { return sessionStorage.getItem(key) ?? initial; } catch { return initial; }
  });
  const set = useCallback((v: string) => {
    setValue(v);
    try { sessionStorage.setItem(key, v); } catch { /* private mode */ }
  }, [key]);
  return [value, set];
}

/** "just now", "4 min ago", "3 h ago", or a date for anything older than a day. */
export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "–";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.round((now - t) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
}

export const fmtNum = (n: number | null | undefined) => (n === null || n === undefined ? "–" : n.toLocaleString());

export function initials(name: string): string {
  const parts = name.replace(/[-_.]/g, " ").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0]?.[1] ?? "")).toUpperCase();
}

/** "data_engineering" -> "Data engineering" */
const ACRONYMS: Record<string, string> = { sql: "SQL", nlp: "NLP", ai: "AI" };
export const humanize = (id: string | null | undefined) =>
  !id ? "–" : ACRONYMS[id] ?? id[0].toUpperCase() + id.slice(1).replaceAll("_", " ");

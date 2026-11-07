import { useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode, type RefObject } from "react";

/** Tracks an element's content width (charts re-render to the real pixel width, so text never scales). */
export function useWidth<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

/** Hover tooltip for a chart host: position follows the pointer, flips near the right edge. */
export function useTip() {
  const [tip, setTip] = useState<{ x: number; y: number; flip: boolean; body: ReactNode } | null>(null);
  function show(e: MouseEvent, host: HTMLElement | null, body: ReactNode) {
    if (!host) return;
    const r = host.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top;
    setTip({ x, y, flip: x > r.width * 0.6, body });
  }
  const node = tip && (
    <div className="tt" role="presentation" style={{ left: tip.flip ? undefined : tip.x + 14, right: tip.flip ? `calc(100% - ${tip.x - 14}px)` : undefined, top: Math.max(0, tip.y - 10) }}>
      {tip.body}
    </div>
  );
  return { show, hide: () => setTip(null), node };
}

export function TipRow({ color, label, value, line }: { color?: string; label: string; value: ReactNode; line?: boolean }) {
  return (
    <div className="tt-row">
      <span>{color && <i className={line ? "sw-line" : "sw-box"} style={{ background: color }} />}{label}</span>
      <b>{value}</b>
    </div>
  );
}

export interface LineSeries { name: string; values: number[]; color: string; wash?: boolean }

/** Single-axis line chart with crosshair tooltip, optional reference lines and end label. */
export function LineChart({ x, series, yMax, yTicks, yFmt = String, height = 220, refs = [], endLabel, label, tip, xEvery }: {
  x: string[]; series: LineSeries[]; yMax: number; yTicks: number[]; yFmt?: (v: number) => string; height?: number;
  refs?: { y: number; label: string }[]; endLabel?: boolean; label: string; tip: (i: number) => ReactNode; xEvery?: number;
}) {
  const [ref, measured] = useWidth<HTMLDivElement>();
  const t = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const W = Math.max(280, measured || 600), H = height;
  const m = { l: 44, r: endLabel ? 56 : 14, t: 14, b: 28 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b, n = x.length;
  const X = (i: number) => m.l + (n < 2 ? iw / 2 : (i * iw) / (n - 1));
  const Y = (v: number) => m.t + ih - (Math.min(v, yMax) / yMax) * ih;
  const labelW = Math.max(40, ...x.map((l) => l.length * 6.4 + 18)); // keep tick labels from colliding
  let every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / labelW))));
  if (xEvery) every = Math.ceil(every / xEvery) * xEvery;
  const ticks: number[] = [];
  for (let i = 0; i < n; i += every) ticks.push(i);

  function move(e: MouseEvent<SVGRectElement>) {
    const b = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect();
    const px = ((e.clientX - b.left) * W) / b.width;
    const i = Math.max(0, Math.min(n - 1, Math.round((px - m.l) / (n > 1 ? iw / (n - 1) : 1))));
    setHover(i);
    t.show(e, ref.current, tip(i));
  }
  return (
    <div className="chart-host" ref={ref}>
      {n > 0 && (
        <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={label}>
          {yTicks.map((v) => (
            <g key={v}>
              {v !== 0 && <line className="gridline" x1={m.l} x2={W - m.r} y1={Y(v)} y2={Y(v)} />}
              <text className="tick" x={m.l - 8} y={Y(v)} dy="0.32em" textAnchor="end">{yFmt(v)}</text>
            </g>
          ))}
          {refs.map((r) => (
            <g key={r.label}>
              <line className="ref" x1={m.l} x2={W - m.r} y1={Y(r.y)} y2={Y(r.y)} />
              <text className="ref-label" x={m.l + 6} y={Y(r.y) - 5}>{r.label}</text>
            </g>
          ))}
          <line className="axis" x1={m.l} x2={W - m.r} y1={Y(0)} y2={Y(0)} />
          {ticks.map((i) => (
            <text key={i} className="tick" x={X(i)} y={H - 8} textAnchor={i === 0 ? "start" : i === n - 1 ? "end" : "middle"}>{x[i]}</text>
          ))}
          {series.map((s) => {
            const d = s.values.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
            const last = s.values[n - 1];
            return (
              <g key={s.name}>
                {s.wash && <path d={`${d}L${X(n - 1)},${Y(0)}L${X(0)},${Y(0)}Z`} fill={`var(--s1-wash)`} />}
                <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                <circle cx={X(n - 1)} cy={Y(last)} r={4} fill={s.color} stroke="var(--chart-surface)" strokeWidth={2} />
                {endLabel && <text className="end-label" x={X(n - 1) + 9} y={Y(last)} dy="0.32em">{yFmt(last)}</text>}
              </g>
            );
          })}
          {hover !== null && (
            <g>
              <line className="crosshair" x1={X(hover)} x2={X(hover)} y1={m.t} y2={m.t + ih} />
              {series.map((s) => <circle key={s.name} cx={X(hover)} cy={Y(s.values[hover])} r={5} fill={s.color} stroke="var(--chart-surface)" strokeWidth={2} />)}
            </g>
          )}
          <rect x={m.l - 10} y={0} width={iw + 20} height={H - m.b} fill="transparent" onMouseMove={move} onMouseLeave={() => { setHover(null); t.hide(); }} />
        </svg>
      )}
      {t.node}
    </div>
  );
}

/** Small multiple: one learner line against a reference line, shared y scale, no axes. */
export function MiniLine({ values, reference, max, label }: { values: number[]; reference: number[]; max: number; label: string }) {
  const W = 240, H = 64, P = 6;
  const path = (a: number[]) => a.map((v, i) => `${i ? "L" : "M"}${(P + (i * (W - 2 * P)) / Math.max(1, a.length - 1)).toFixed(1)},${(H - P - (Math.min(v, max) / max) * (H - 2 * P)).toFixed(1)}`).join("");
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label={label}>
      <line className="axis" x1={P} x2={W - P} y1={H - P} y2={H - P} vectorEffect="non-scaling-stroke" />
      <path d={path(reference)} fill="none" stroke="var(--ref)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
      <path d={path(values)} fill="none" stroke="var(--s1)" strokeWidth={2} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Horizontal bars for shares (0..1) with an optional vertical reference line. */
export function HBars({ rows, refValue, fmt = (v) => `${(v * 100).toFixed(1)}%` }: {
  rows: { key: string; label: ReactNode; value: number | null; on?: boolean; title?: string }[];
  refValue?: number; fmt?: (v: number) => string;
}) {
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hbar-row" key={r.key} title={r.title}>
          <span className={`hbar-label${r.on ? " strong" : ""}`}>{r.label}</span>
          <div className="hbar-track">
            {r.value !== null && <div className={`hbar${r.on ? " on" : ""}`} style={{ width: `${Math.max(0, Math.min(1, r.value)) * 100}%` }} />}
            {refValue !== undefined && <div className="hbar-ref" style={{ left: `${refValue * 100}%` }} />}
          </div>
          <span className="hbar-val">{r.value === null ? "–" : fmt(r.value)}</span>
        </div>
      ))}
      <div className="hbar-axis" aria-hidden="true"><span /><div><span style={{ left: 0 }}>0%</span><span style={{ left: "50%" }}>50%</span><span style={{ left: "100%" }}>100%</span></div><span /></div>
    </div>
  );
}

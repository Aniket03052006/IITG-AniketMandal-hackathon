import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { RebalancerTimeline } from "../../api/types";
import { areaPath, linePath, nearestIndex, pp, share, spreadLabels, stackLayers, type SeriesSpec } from "../../lib/rebalancer";

export type ChartView = "stack" | "active";

const W = 960;
const H = 380;
const PAD = { l: 52, r: 64, t: 14, b: 30 };
const PLOT_W = W - PAD.l - PAD.r;
const PLOT_H = H - PAD.t - PAD.b;

const dayLabel = (ms: number) => new Date(ms).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/**
 * The weights of every stock at every cycle. Two views of the same numbers: the stacked weights (every column adds to 100 %) and each stock's active weight against its
 * benchmark. The chart is never the only carrier of the figures: the ticker is printed beside each band and the table beneath lists the exact weights.
 */
export function WeightsChart({ timeline, series, view, cycle, onCycle, focus, onFocus }: {
  timeline: RebalancerTimeline;
  series: SeriesSpec[];
  view: ChartView;
  cycle: number;
  onCycle: (i: number) => void;
  focus: string | null;
  onFocus: (ticker: string | null) => void;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const cycles = timeline.cycles;
  const geo = useMemo(() => {
    const times = cycles.map((c) => new Date(c.at).getTime());
    const t0 = times[0] ?? 0;
    const span = Math.max(1, (times[times.length - 1] ?? 1) - t0);
    const xs = times.map((t) => PAD.l + ((t - t0) / span) * PLOT_W);
    const weights = cycles.map((c) => c.weights);
    const layers = stackLayers(weights, series);
    const active = series.map((s) => cycles.map((c) => (c.weights[s.index] ?? 0) - s.benchmark));
    const reach = Math.max(0.01, ...active.flat().map((v) => Math.abs(v)));
    const bound = Math.ceil(reach * 100) / 100; // the next whole point of the index, so the axis ticks are round
    const day = 86_400_000;
    const days: number[] = [];
    for (let d = Math.ceil(t0 / day) * day; d <= t0 + span; d += day) days.push(d);
    return { times, t0, span, xs, layers, active, bound, days };
  }, [cycles, series]);

  if (cycles.length < 2) return <p className="text-sm text-muted">Too few cycles to draw a timeline.</p>;

  const yStack = (v: number) => PAD.t + (1 - v) * PLOT_H;
  const yActive = (v: number) => PAD.t + (0.5 - v / (2 * geo.bound)) * PLOT_H;
  const x = (t: number) => PAD.l + ((t - geo.t0) / geo.span) * PLOT_W;
  const last = cycles.length - 1;
  const at = Math.min(Math.max(cycle, 0), last);
  const shown = hover ?? at;

  // direct labels, one per stock, at the right edge, pushed apart so none overlaps
  const wantY = series.map((_, k) => (view === "stack"
    ? yStack(((geo.layers[k]!.top[last] ?? 0) + (geo.layers[k]!.bottom[last] ?? 0)) / 2)
    : yActive(geo.active[k]![last] ?? 0)));
  const labelY = spreadLabels(wantY, 11, PAD.t + 5, H - PAD.b - 3);

  /** The cycle under the pointer, or null when it is outside the plot (the labels column, the axes). */
  const locate = (e: PointerEvent<SVGSVGElement>): number | null => {
    const box = ref.current?.getBoundingClientRect();
    if (!box || box.width === 0) return null;
    const px = ((e.clientX - box.left) / box.width) * W;
    const py = ((e.clientY - box.top) / box.height) * H;
    if (px < PAD.l || px > W - PAD.r || py < PAD.t || py > H - PAD.b) return null;
    return nearestIndex(px, PAD.l, W - PAD.r, geo.xs);
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key === "ArrowLeft") { onCycle(Math.max(0, at - 1)); e.preventDefault(); }
    else if (e.key === "ArrowRight") { onCycle(Math.min(last, at + 1)); e.preventDefault(); }
    else if (e.key === "Home") { onCycle(0); e.preventDefault(); }
    else if (e.key === "End") { onCycle(last); e.preventDefault(); }
  };

  const top = series.reduce((best, s) => ((cycles[at]?.weights[s.index] ?? 0) > (cycles[at]?.weights[best.index] ?? 0) ? s : best), series[0]!);
  const summary = `${view === "stack" ? "Stacked weights" : "Active weights against the equal-weight benchmark"} of ${series.length} stocks over ${cycles.length} cycles, ${dayLabel(geo.t0)} to ${dayLabel(geo.t0 + geo.span)}. `
    + `At the selected cycle the largest weight is ${top.ticker} at ${share(cycles[at]?.weights[top.index] ?? 0)}. Exact figures are in the table below.`;

  return (
    <figure className="rb-chart">
      <div className="scroll-x">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={summary} tabIndex={0} onKeyDown={onKey} className="rb-svg"
        onPointerMove={(e) => setHover(locate(e))} onPointerLeave={() => setHover(null)} onClick={(e) => { const i = locate(e as unknown as PointerEvent<SVGSVGElement>); if (i != null) onCycle(i); }}>
        {/* value axis */}
        {(view === "stack" ? [0, 0.25, 0.5, 0.75, 1] : [-geo.bound, -geo.bound / 2, 0, geo.bound / 2, geo.bound]).map((v) => {
          const y = view === "stack" ? yStack(v) : yActive(v);
          return (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} className={view === "active" && v === 0 ? "rb-zero" : "rb-grid"} />
              <text x={PAD.l - 8} y={y + 4} textAnchor="end" className="rb-tick">{view === "stack" ? `${Math.round(v * 100)}%` : pp(v, 1).replace(" pp", "")}</text>
            </g>
          );
        })}
        {view === "active" && <text x={PAD.l} y={PAD.t - 3} className="rb-tick">pp vs equal weight</text>}
        {/* time axis: a tick at each day start */}
        {geo.days.map((d) => (
          <g key={d}>
            <line x1={x(d)} x2={x(d)} y1={H - PAD.b} y2={H - PAD.b + 4} className="rb-grid" />
            <text x={x(d)} y={H - 10} textAnchor="middle" className="rb-tick">{dayLabel(d)}</text>
          </g>
        ))}
        {view === "stack" && geo.layers.map((l) => (
          <path key={l.spec.ticker} d={areaPath(geo.xs, l.top, l.bottom, yStack)} className="rb-band" data-dim={focus != null && focus !== l.spec.ticker ? "true" : undefined}
            onPointerEnter={() => onFocus(l.spec.ticker)} onPointerLeave={() => onFocus(null)} style={{ fill: l.spec.fill }}>
            <title>{`${l.spec.ticker} · ${l.spec.name} · ${l.spec.sector}`}</title>
          </path>
        ))}
        {view === "active" && series.map((s, k) => (
          <g key={s.ticker} onPointerEnter={() => onFocus(s.ticker)} onPointerLeave={() => onFocus(null)}>
            <path d={linePath(geo.xs, geo.active[k]!, yActive)} className="rb-line-hit" />
            <path d={linePath(geo.xs, geo.active[k]!, yActive)} className="rb-line" data-dim={focus != null && focus !== s.ticker ? "true" : undefined}
              data-focus={focus === s.ticker ? "true" : undefined} style={{ stroke: s.stroke }}>
              <title>{`${s.ticker} · ${s.name}`}</title>
            </path>
          </g>
        ))}
        {/* direct labels */}
        {series.map((s, k) => (
          <g key={s.ticker} className="rb-label" data-dim={focus != null && focus !== s.ticker ? "true" : undefined}
            onPointerEnter={() => onFocus(s.ticker)} onPointerLeave={() => onFocus(null)}>
            <line x1={W - PAD.r + 2} x2={W - PAD.r + 8} y1={wantY[k]!} y2={labelY[k]! - 3.5} style={{ stroke: s.stroke }} className="rb-leader" />
            <rect x={W - PAD.r + 8} y={labelY[k]! - 9} width={PAD.r - 8} height="12" fill="transparent" />
            <text x={W - PAD.r + 11} y={labelY[k]!} className="rb-ticker">{s.ticker}</text>
          </g>
        ))}
        {/* the selected cycle and the one under the pointer */}
        {hover != null && hover !== at && <line x1={geo.xs[hover]} x2={geo.xs[hover]} y1={PAD.t} y2={H - PAD.b} className="rb-hover" />}
        <line x1={geo.xs[at]} x2={geo.xs[at]} y1={PAD.t} y2={H - PAD.b} className="rb-cursor" />
        <circle cx={geo.xs[at]} cy={PAD.t} r="4" className="rb-cursor-dot" />
      </svg>
      </div>
      <figcaption className="rb-caption">
        <span className="num">{shown === at ? "Selected" : "Pointing at"} cycle {shown + 1} of {cycles.length}</span>
        <span className="num">{new Date(cycles[shown]!.at).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC</span>
        <span className="num">turnover {share(cycles[shown]!.turnover)}</span>
      </figcaption>
    </figure>
  );
}

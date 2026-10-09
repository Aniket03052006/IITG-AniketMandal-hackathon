import clsx from "clsx";
import type { RebalancerTimeline } from "../../api/types";
import { linePath, pp, type SeriesSpec } from "../../lib/rebalancer";

const W = 140;
const H = 44;

/** Small multiples: one tile per stock, its weight minus its benchmark over time, all on the same vertical scale so the tiles can be compared. */
export function TiltTiles({ timeline, series, cycle, focus, onHover, onSelect }: {
  timeline: RebalancerTimeline;
  series: SeriesSpec[];
  cycle: number;
  focus: string | null;
  onHover: (t: string | null) => void;
  onSelect: (t: string) => void;
}) {
  const cycles = timeline.cycles;
  if (cycles.length < 2) return null;
  const active = series.map((s) => cycles.map((c) => (c.weights[s.index] ?? 0) - s.benchmark));
  const reach = Math.max(0.005, ...active.flat().map((v) => Math.abs(v)));
  const xs = cycles.map((_, i) => 2 + (i / (cycles.length - 1)) * (W - 4));
  const y = (v: number) => H / 2 - (v / reach) * (H / 2 - 3);
  const at = Math.min(cycle, cycles.length - 1);
  return (
    <ul className="rb-tiles" aria-label="Active weight of each stock over time, same scale">
      {series.map((s, k) => {
        const now = active[k]![at] ?? 0;
        return (
          <li key={s.ticker}>
            <button type="button" className={clsx("rb-tile", focus === s.ticker && "rb-tile-on")} aria-pressed={focus === s.ticker}
              onClick={() => onSelect(s.ticker)} onMouseEnter={() => onHover(s.ticker)} onMouseLeave={() => onHover(null)}>
              <span className="rb-tile-head">
                <b className="num">{s.ticker}</b>
                <span className={clsx("num", now > 5e-4 ? "text-pos" : now < -5e-4 ? "text-neg" : "text-muted")}>{pp(now)}</span>
              </span>
              <svg viewBox={`0 0 ${W} ${H}`} className="rb-spark" role="img" aria-label={`${s.ticker} active weight over time, now ${pp(now)}`}>
                <line x1="0" x2={W} y1={H / 2} y2={H / 2} className="rb-zero" />
                <path d={linePath(xs, active[k]!, y)} className="rb-spark-line" style={{ stroke: s.stroke }} />
                <circle cx={xs[at]} cy={y(now)} r="2.6" style={{ fill: s.stroke }} />
              </svg>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

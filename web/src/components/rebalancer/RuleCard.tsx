import type { RebalancerOverview, RebalancerParams } from "../../api/types";
import { share } from "../../lib/rebalancer";

const W = 320;
const H = 170;
const PAD = { l: 38, r: 10, t: 10, b: 26 };

/** The rule in words and as a curve: what one stock's weight would be at each sentiment score while every other stock sits at zero. */
export function RuleCard({ overview, params }: { overview: RebalancerOverview; params: RebalancerParams }) {
  const { lower, upper, benchmark } = overview.bounds as Record<string, number>;
  const c = overview.curve;
  const ymax = Math.max(upper! * 1.1, ...c.map((p) => p.target!));
  const x = (s: number) => PAD.l + ((s + 1) / 2) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - v / ymax) * (H - PAD.t - PAD.b);
  const path = (key: "target" | "bounded") => c.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.score!).toFixed(1)} ${y(p[key]!).toFixed(1)}`).join(" ");
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
      <ol className="m-0 list-none space-y-3 p-0 text-sm text-ink-2">
        <li><b className="text-ink">1 · Score.</b> For each stock, the sentiment of the reports that name it, each report fading with a half-life of <span className="num">{params.half_life_hours} h</span>.
          One source counts for at most one vote, and a few pseudo-reports at zero pull thin evidence toward neutral. The score lies between −1 and +1.</li>
        <li><b className="text-ink">2 · Tilt.</b> Start from equal weights and multiply each by <span className="num">e<sup>{params.tilt} × score</sup></span>, then rescale to 100 %. Positive sentiment raises a weight and negative lowers it; zero leaves it at its benchmark.</li>
        <li><b className="text-ink">3 · Bounds.</b> No stock goes below <span className="num">{share(lower!)}</span> or above <span className="num">{share(upper!)}</span> (at most {share(overview.bounds.max_active_ratio!, 0)} over or under its <span className="num">{share(benchmark!)}</span> benchmark, inside a {share(overview.bounds.floor!, 0)} floor and {share(overview.bounds.cap!, 0)} cap); the nearest legal weights are used.</li>
        <li><b className="text-ink">4 · Turnover.</b> The index moves toward that target by at most <span className="num">{share(params.max_turnover)}</span> of its value per cycle, and does not trade a move smaller than <span className="num">{share(overview.bounds.min_trade!)}</span>.</li>
        <li className="text-xs text-muted">Every number is a judgement prior written before any result was looked at. None is fitted, and the rule is a transparent mapping, not a forecast.</li>
      </ol>
      <figure>
        <svg viewBox={`0 0 ${W} ${H}`} className="rb-curve" role="img"
          aria-label={`Weight of one stock against its sentiment score: ${share(c[0]!.bounded!)} at −1, ${share(benchmark!)} at 0, ${share(c[c.length - 1]!.bounded!)} at +1, with the bounds at ${share(lower!)} and ${share(upper!)}.`}>
          {[lower!, benchmark!, upper!].map((v) => (
            <g key={v}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} className={v === benchmark ? "rb-zero" : "rb-grid"} strokeDasharray={v === benchmark ? undefined : "3 3"} />
              <text x={PAD.l - 5} y={y(v) + 3.5} textAnchor="end" className="rb-tick">{(v * 100).toFixed(1)}%</text>
            </g>
          ))}
          <line x1={x(0)} x2={x(0)} y1={PAD.t} y2={H - PAD.b} className="rb-grid" />
          <path d={path("target")} className="rb-curve-raw" />
          <path d={path("bounded")} className="rb-curve-line" />
          {[-1, 0, 1].map((s) => <text key={s} x={x(s)} y={H - 8} textAnchor="middle" className="rb-tick">{s > 0 ? "+" : s < 0 ? "−" : ""}{Math.abs(s)}</text>)}
        </svg>
        <figcaption className="mt-1 text-xs text-muted">One stock&apos;s weight against its score (others at zero). Dashed: the tilt alone; solid: after the bounds.</figcaption>
      </figure>
    </div>
  );
}

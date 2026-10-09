import type { RebalancerBacktest, RebalancerBacktestView } from "../../api/types";
import { linePath } from "../../lib/rebalancer";
import { StateNotice } from "../StateNotice";

const pct = (v: number, d = 2) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`;
const W = 420;
const H = 150;
const PAD = { l: 44, r: 10, t: 10, b: 24 };

function Curve({ b }: { b: RebalancerBacktest }) {
  const all = [...b.cumulative_rebalanced, ...b.cumulative_benchmark, 0];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = Math.max(hi - lo, 0.002);
  const xs = b.dates.map((_, i) => PAD.l + (i / Math.max(1, b.dates.length - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="rb-curve" role="img"
        aria-label={`Cumulative net return over ${b.dates.length} sessions: rebalanced index ${pct(b.summary.rebalanced_return)}, equal-weight benchmark ${pct(b.summary.benchmark_return)}.`}>
        <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} className="rb-zero" />
        {[hi, lo].map((v) => <text key={v} x={PAD.l - 5} y={y(v) + 3.5} textAnchor="end" className="rb-tick">{pct(v, 1)}</text>)}
        <path d={linePath(xs, b.cumulative_benchmark, y)} className="rb-bt-bench" />
        <path d={linePath(xs, b.cumulative_rebalanced, y)} className="rb-bt-index" />
        <text x={PAD.l} y={H - 7} className="rb-tick">{b.dates[0]}</text>
        <text x={W - PAD.r} y={H - 7} textAnchor="end" className="rb-tick">{b.dates[b.dates.length - 1]}</text>
      </svg>
      <figcaption className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted">
        <span><i className="rb-key rb-key-index" aria-hidden="true" /> Rebalanced index</span>
        <span><i className="rb-key rb-key-bench" aria-hidden="true" /> Equal-weight benchmark</span>
      </figcaption>
    </figure>
  );
}

/** An illustration of the mechanics over the replay window, with two controls beside it so a few sessions cannot be mistaken for skill. */
export function BacktestCard({ view }: { view: RebalancerBacktestView }) {
  const b = view.backtest;
  if (!b) return <StateNotice tone="info" what="No back-test has been built." why={view.reason ?? "The back-test needs the price files, which are not redistributed."} />;
  const s = b.summary;
  const p = b.placebo;
  const inside = p.active_return_percentile > 0.05 && p.active_return_percentile < 0.95;
  return (
    <div>
      {view.status === "STALE" && <div className="mb-4"><StateNotice tone="warn" what="This back-test is out of date." why={view.reason ?? "The weights changed since it was built."} /></div>}
      <p className="mb-4 text-sm text-ink-2">
        An <b className="text-ink">illustration of the mechanics</b> over {b.dates.length} trading sessions ({b.dates[0]} to {b.dates[b.dates.length - 1]}). Each session uses the weights set at the previous close,
        after a {b.cost_bps} bp one-way cost on turnover. {b.dates.length} sessions cannot separate skill from luck, which is what the two controls below are for.
      </p>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
        <dl className="rb-dl">
          <div><dt>Rebalanced index</dt><dd className="num">{pct(s.rebalanced_return)}</dd></div>
          <div><dt>Equal-weight benchmark</dt><dd className="num">{pct(s.benchmark_return)}</dd></div>
          <div><dt>Difference</dt><dd className="num">{pct(s.active_return)}</dd></div>
          <div><dt>Mean daily turnover</dt><dd className="num">{(s.mean_daily_turnover * 100).toFixed(1)}%</dd></div>
          <div><dt>Cost charged</dt><dd className="num">{pct(-s.total_cost)}</dd></div>
          <div title="Spearman correlation between a stock's score at the previous close and its next-session return, averaged over the days it is defined">
            <dt>Rank IC (score → next-day return)</dt><dd className="num">{b.rank_ic.mean == null ? "n/a" : b.rank_ic.mean.toFixed(3)} <span className="text-xs text-muted">over {b.rank_ic.days} days</span></dd>
          </div>
          <div className="rb-dl-wide">
            <dt>Control: the same scores given to the wrong companies</dt>
            <dd>
              <span className="num">{p.runs}</span> shuffles give a difference between <span className="num">{pct(p.active_return_p05)}</span> and <span className="num">{pct(p.active_return_p95)}</span> (5th to 95th percentile).
              The real difference sits at the <span className="num">{Math.round(p.active_return_percentile * 100)}th</span> percentile.{" "}
              <b>{inside ? "That is within what shuffled sentiment produces by chance, so this window shows no evidence the sentiment tilt helps." : "That is outside the shuffled range, but with so few sessions it is still not evidence of skill."}</b>
            </dd>
          </div>
        </dl>
        <Curve b={b} />
      </div>
      <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-muted">{b.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
    </div>
  );
}

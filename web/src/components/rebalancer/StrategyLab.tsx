import type { LabCell, LabStrategy, RebalancerLabView } from "../../api/types";
import { VERDICT_TEXT } from "../../lib/rebalancer";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";
import { LabCurves } from "./LabCurves";
import { SensitivityGrid } from "./SensitivityGrid";

const pct = (v: number | null | undefined, d = 2) => (v == null ? "–" : `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`);
const plain = (v: number | null | undefined, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)}%`);

function Row({ s }: { s: LabStrategy }) {
  const m = s.metrics;
  return (
    <tr>
      <th scope="row">
        <span className="font-medium">{s.label}</span>
        {s.experimental && <> <StatusTag tone="warn">Experimental</StatusTag></>}
        {s.kind === "REFERENCE" && <> <StatusTag tone="demo">Reference</StatusTag></>}
      </th>
      <td className="num text-right">{pct(m.cumulative_return)}</td>
      <td className="num text-right">{s.id === "equal_weight" ? "benchmark" : pct(m.active_return)}</td>
      <td className="num text-right">{plain(m.annualised_vol)}</td>
      <td className="num text-right">{pct(m.max_drawdown)}</td>
      <td className="num text-right">{plain(m.hit_rate, 0)}</td>
      <td className="num text-right">{plain(m.mean_daily_turnover)}</td>
      <td className="num text-right">{pct(-m.total_cost)}</td>
      <td className="num text-right">{m.rank_ic == null ? "–" : m.rank_ic.toFixed(2)}</td>
      <td className="num text-right">{s.windows_total ? `${s.windows_positive} of ${s.windows_total}` : "–"}</td>
      <td>{s.placebo ? <><span className="num">{Math.round(s.placebo.active_return_percentile * 100)}th</span> percentile · <b>{VERDICT_TEXT[s.verdict ?? ""] ?? s.verdict}</b></> : <span className="text-muted">no placebo (does not use scores)</span>}</td>
    </tr>
  );
}

/** The strategy lab: the same window, prices, costs and placebo for every strategy; then how fragile the result is to the parameters. An illustration of mechanics, never evidence of skill. */
export function StrategyLab({ view }: { view: RebalancerLabView }) {
  const lab = view.lab;
  if (!lab) return <StateNotice tone="info" what="The strategy lab has not been built." why={view.reason ?? "The lab needs the price files, which are not redistributed."} next={<code className="text-xs">make rebalancer-risk-inputs rebalancer-lab</code>} />;
  const g = lab.grid;
  const base = lab.strategies.find((s) => s.id === "sentiment");
  const win = lab.strategies[0]!.windows;
  const cells = (list: LabCell[], f: (c: LabCell) => string) => (r: string, c: string) => list.find((x) => f(x) === `${r}|${c}`);
  const hl = (c: LabCell) => `${c.half_life_hours}|${c.max_turnover}`;
  const tl = (c: LabCell) => `${c.tilt}|${c.max_active_ratio}`;
  const hours = [...new Set(g.half_life_by_turnover.map((c) => c.half_life_hours))];
  const caps = [...new Set(g.half_life_by_turnover.map((c) => c.max_turnover))];
  const tilts = [...new Set(g.tilt_by_position_limit.map((c) => c.tilt))];
  const limits = [...new Set(g.tilt_by_position_limit.map((c) => c.max_active_ratio))];
  const reach = Math.max(0.002, Math.abs(g.active_min), Math.abs(g.active_max));
  const shippedHl = (c: LabCell) => base != null && c.half_life_hours === lab.params.half_life_hours && c.max_turnover === lab.params.max_turnover;
  const shippedTl = (c: LabCell) => c.tilt === lab.params.tilt && c.max_active_ratio === 0.5;
  return (
    <div className="space-y-6">
      {view.status === "STALE" && <StateNotice tone="warn" what="This lab is out of date." why={view.reason ?? "The weights changed since it was built."} />}
      <StateNotice tone="info" what={`${lab.dates.length} sessions: an illustration of the mechanics, not evidence of skill.`}
        why={<>{lab.dates[0]} to {lab.dates[lab.dates.length - 1]}, after a {lab.cost_bps} bp one-way cost. Every strategy has its own shuffled-score placebo; a result inside the shuffled range is what chance gives for this window. The verdict is computed, never chosen.</>} />

      <section aria-label="Strategy comparison" className="space-y-3">
        <h2 className="text-lg">Same window, same costs</h2>
        <div className="scroll-x">
          <table className="dtable min-w-[64rem]">
            <caption className="sr-only">Every strategy over the same sessions: return, difference from equal weight, volatility, drawdown, hit rate, turnover, cost, rank IC, rolling windows and the placebo verdict</caption>
            <thead>
              <tr>
                <th scope="col">Strategy</th>
                <th scope="col" className="text-right">Return</th>
                <th scope="col" className="text-right">vs equal weight</th>
                <th scope="col" className="text-right" title="daily standard deviation x sqrt(252); ten sessions, so indicative only">Vol (ann.)</th>
                <th scope="col" className="text-right">Max drawdown</th>
                <th scope="col" className="text-right" title="share of sessions on which it beat equal weight">Hit rate</th>
                <th scope="col" className="text-right">Turnover / day</th>
                <th scope="col" className="text-right">Cost</th>
                <th scope="col" className="text-right" title="Spearman correlation of the score with the next session's return">Rank IC</th>
                <th scope="col" className="text-right" title="rolling five-session windows that ended ahead of equal weight">Windows ahead</th>
                <th scope="col">Against shuffled scores</th>
              </tr>
            </thead>
            <tbody>{lab.strategies.map((s) => <Row key={s.id} s={s} />)}</tbody>
          </table>
        </div>
        <LabCurves strategies={lab.strategies} dates={lab.dates} />
      </section>

      <section aria-label="Windows" className="space-y-3">
        <h2 className="text-lg">Different windows of the same ten sessions</h2>
        <div className="scroll-x">
          <table className="dtable min-w-[40rem]">
            <caption className="sr-only">Return in excess of equal weight, per window, per strategy</caption>
            <thead>
              <tr>
                <th scope="col">Window</th>
                {lab.strategies.filter((s) => s.id !== "equal_weight").map((s) => <th key={s.id} scope="col" className="text-right">{s.label.replace(/ \(.*\)$/, "")}</th>)}
              </tr>
            </thead>
            <tbody>
              {win.map((w, i) => (
                <tr key={w.label}>
                  <th scope="row"><span className="font-medium">{w.label}</span><span className="block text-xs text-muted">{w.start} to {w.end}</span></th>
                  {lab.strategies.filter((s) => s.id !== "equal_weight").map((s) => <td key={s.id} className="num text-right">{pct(s.windows[i]!.active_return)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-label="Sensitivity" className="space-y-4">
        <h2 className="text-lg">How fragile is the baseline to its parameters?</h2>
        <p className="text-sm text-ink-2">
          The baseline re-run at {g.cells_total} settings: <b className="num">{g.cells_positive}</b> of {g.cells_total} ended ahead of equal weight, <b className="num">{g.cells_outside_placebo_range}</b> fell outside their own 5th to 95th
          placebo range, and about <span className="num">{g.expected_outside_by_chance.toFixed(1)}</span> would by chance alone. Being ahead is not the test: shuffled scores at the shipped setting land anywhere from <span className="num">{pct(base?.placebo?.active_return_p05)}</span> to <span className="num">{pct(base?.placebo?.active_return_p95)}</span> of
          equal weight. <b>The best cell is the luckiest cell, not a recommendation</b>; the shipped parameters were fixed before any result existed and are not changed by this grid.
        </p>
        <SensitivityGrid title="Report half-life by turnover cap (tilt as shipped)" rowLabel="Half-life" colLabel="turnover cap" rows={hours.map((h) => ({ key: String(h), label: `${h} h half-life` }))}
          cols={caps.map((c) => ({ key: String(c), label: `${(c * 100).toFixed(0)}% cap` }))} cell={cells(g.half_life_by_turnover, hl)} reach={reach} shipped={shippedHl} />
        <SensitivityGrid title="Tilt by position limit (half-life and turnover cap as shipped)" rowLabel="Tilt" colLabel="position limit" rows={tilts.map((t) => ({ key: String(t), label: `tilt ${t}` }))}
          cols={limits.map((l) => ({ key: String(l), label: `±${(l * 100).toFixed(0)}% of benchmark` }))} cell={cells(g.tilt_by_position_limit, tl)} reach={reach} shipped={shippedTl} />
        <p className="text-xs text-muted">Each cell: difference from equal weight, and where it sits among {g.placebo_runs} shuffled-score runs of the same setting.</p>
      </section>

      <section aria-label="Cost" className="space-y-2">
        <h2 className="text-lg">Does the baseline survive trading costs?</h2>
        <div className="scroll-x">
          <table className="dtable min-w-[28rem]">
            <caption className="sr-only">Baseline return and difference from equal weight at four one-way costs</caption>
            <thead><tr><th scope="col">One-way cost</th><th scope="col" className="text-right">Baseline</th><th scope="col" className="text-right">Equal weight</th><th scope="col" className="text-right">Difference</th></tr></thead>
            <tbody>{lab.cost_sensitivity.map((c) => <tr key={c.cost_bps}><th scope="row" className="num">{c.cost_bps} bp</th><td className="num text-right">{pct(c.strategy_return)}</td><td className="num text-right">{pct(c.benchmark_return)}</td><td className="num text-right">{pct(c.active_return)}</td></tr>)}</tbody>
          </table>
        </div>
      </section>

      <p className="text-sm text-ink-2">
        The sentiment-and-impact strategy can re-weight only the <span className="num">{lab.impact_reports}</span> of <span className="num">{lab.reports_used}</span> reports that carry an impact score; a report without one counts as the lowest impact.
      </p>
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{lab.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
    </div>
  );
}

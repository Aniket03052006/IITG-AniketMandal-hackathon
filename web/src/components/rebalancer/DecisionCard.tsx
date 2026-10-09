import clsx from "clsx";
import type { TradeDecision } from "../../api/types";
import { ageText, pp, share, tradeText } from "../../lib/rebalancer";
import { StatusTag } from "../ui";
import { ConstraintBadge } from "./ConstraintBadge";
import { DriverRow } from "./DriverRow";

const QUALITY = { NONE: "No evidence", THIN: "Thin evidence", OK: "Evidence adequate" } as const;

/** One stock as a decision: the trade, the sentence that explains it, the evidence behind it with its quality, how fresh it is, whether it conflicts, and the rules that held it back. */
export function DecisionCard({ d, accepted, onAccept, selectable, selected, id }: { d: TradeDecision; accepted: boolean; onAccept: (on: boolean) => void; selectable: boolean; selected: boolean; id: string }) {
  const tone = d.side === "BUY" ? "text-pos" : d.side === "SELL" ? "text-neg" : "text-ink-2";
  return (
    <article id={id} className={clsx("rb-decision", selected && "rb-decision-on")} aria-label={`${d.ticker}: ${tradeText(d)}`} data-side={d.side}>
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="m-0 text-base"><span className="num">{d.ticker}</span> <span className="font-normal text-muted">{d.name}</span></h3>
        <span className={clsx("num font-semibold", tone)}>{tradeText(d)}</span>
        <span className="num text-sm text-ink-2">{share(d.before)} → {share(d.after)}</span>
        {selectable && d.side !== "HOLD" && (
          <label className="ml-auto inline-flex items-center gap-2 text-sm">
            <input type="checkbox" checked={accepted} onChange={(e) => onAccept(e.target.checked)} />
            Include in approval
          </label>
        )}
      </header>
      <p className="mt-2 text-sm text-ink-2">{d.explanation}</p>
      <ul className="m-0 mt-2 flex list-none flex-wrap gap-1.5 p-0" aria-label="Evidence and constraints">
        <li><StatusTag tone={d.evidence_quality === "OK" ? "ok" : d.evidence_quality === "THIN" ? "warn" : "demo"}>{QUALITY[d.evidence_quality]}</StatusTag></li>
        {d.newest_age_hours != null && <li><StatusTag tone={d.stale ? "warn" : "demo"}>{d.stale ? "Stale: " : "Newest report "}{ageText(d.newest_age_hours)} old</StatusTag></li>}
        {d.conflicting && <li><StatusTag tone="warn">Reports disagree · {Math.round(d.positive_share * 100)}% positive / {Math.round(d.negative_share * 100)}% negative</StatusTag></li>}
        {d.liquidity_flag && d.participation != null && <li><StatusTag tone="warn">Large against volume · {(d.participation * 100).toFixed(1)}% of a day</StatusTag></li>}
        {d.binding.map((b) => <li key={b.code}><ConstraintBadge effect={b} /></li>)}
      </ul>
      <dl className="rb-facts">
        <div><dt>Sentiment score</dt><dd className="num">{d.score >= 0 ? "+" : "−"}{Math.abs(d.score).toFixed(3)}</dd></div>
        <div><dt>Reports · sources</dt><dd className="num">{d.reports} · {d.sources}</dd></div>
        <div><dt>Target</dt><dd className="num">{share(d.target)}</dd></div>
        <div><dt>Est. cost</dt><dd className="num">{(d.est_cost * 1e4).toFixed(2)} bp of the index</dd></div>
        <div><dt>Mock notional</dt><dd className="num">${(d.notional_usd / 1e6).toFixed(1)} M{d.participation != null ? ` (${(d.participation * 100).toFixed(2)}% of daily volume)` : ""}</dd></div>
      </dl>
      {d.drivers.length > 0 && (
        <details className="disclosure mt-2" open={d.side !== "HOLD" && d.drivers.length <= 3}>
          <summary>The {d.drivers.length < d.reports ? `${d.drivers.length} largest of ${d.reports}` : d.reports} report{d.reports === 1 ? "" : "s"} behind it ({pp(d.score, 1).replace(" pp", "")} score)</summary>
          <ol className="m-0 mt-1 list-none divide-y divide-rule p-0">{d.drivers.map((r) => <DriverRow key={r.signal_id} d={r} showTime />)}</ol>
        </details>
      )}
    </article>
  );
}

import clsx from "clsx";
import type { TradeDecision } from "../../api/types";
import { pp, share, tradeText, type SeriesSpec } from "../../lib/rebalancer";
import { ConstraintBadge } from "./ConstraintBadge";

/** Where a weight sits between the lowest and highest weight this strategy allows it. The words (and the title) carry the figures; the bar only shows the position. */
function Headroom({ d }: { d: TradeDecision }) {
  const span = Math.max(d.upper - d.lower, 1e-9);
  const at = Math.min(1, Math.max(0, (d.after - d.lower) / span)) * 100;
  return (
    <span className="rb-range" role="img" aria-label={`${share(d.after)}, allowed ${share(d.lower)} to ${share(d.upper)}`} title={`${share(d.after)} within ${share(d.lower)} to ${share(d.upper)}`}>
      <i style={{ left: `${at}%` }} />
    </span>
  );
}

/** Before, the weight the rule asked for, and after, for every stock, with the trade and the rules that held it back. */
export function AllocationTable({ rows, series, selected, onSelect }: { rows: TradeDecision[]; series: SeriesSpec[]; selected: string | null; onSelect: (t: string) => void }) {
  const by = new Map(series.map((s) => [s.ticker, s]));
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[52rem]">
        <caption className="sr-only">Every stock: weight before this cycle, the weight the rule asked for, the weight after the turnover limit, the trade and the rules that held it back</caption>
        <thead>
          <tr>
            <th scope="col">Stock</th>
            <th scope="col" className="text-right">Before</th>
            <th scope="col" className="text-right">Target</th>
            <th scope="col" className="text-right">After</th>
            <th scope="col">Trade</th>
            <th scope="col">Room</th>
            <th scope="col">Held back by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => {
            const s = by.get(d.ticker);
            return (
              <tr key={d.ticker} className={clsx("rb-row", selected === d.ticker && "rb-row-on")} aria-label={d.ticker}>
                <th scope="row">
                  <button type="button" className="rb-stock" aria-pressed={selected === d.ticker} onClick={() => onSelect(d.ticker)}>
                    <i className="rb-swatch" style={{ background: s ? s.fill : "var(--color-muted)" }} aria-hidden="true" />
                    <b className="num">{d.ticker}</b>
                    <span className="rb-name text-muted">{d.name}</span>
                  </button>
                </th>
                <td className="num text-right">{share(d.before)}</td>
                <td className="num text-right">{share(d.target)}</td>
                <td className="num text-right font-medium">{share(d.after)}</td>
                <td>
                  <span className={clsx("num", d.side === "BUY" && "text-pos", d.side === "SELL" && "text-neg")}>{tradeText(d)}</span>
                </td>
                <td><Headroom d={d} /></td>
                <td>
                  {d.binding.length === 0 ? <span className="text-muted">nothing</span> : <span className="flex flex-wrap gap-1">{d.binding.map((b) => <ConstraintBadge key={b.code} effect={b} />)}</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Index</th>
            <td className="num text-right">{share(rows.reduce((a, d) => a + d.before, 0))}</td>
            <td className="num text-right">{share(rows.reduce((a, d) => a + d.target, 0))}</td>
            <td className="num text-right">{share(rows.reduce((a, d) => a + d.after, 0))}</td>
            <td className="num">{pp(rows.reduce((a, d) => a + Math.abs(d.trade), 0) / 2)} traded</td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

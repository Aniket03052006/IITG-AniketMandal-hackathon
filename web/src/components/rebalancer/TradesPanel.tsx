import type { RebalanceCycleDetail } from "../../api/types";
import { pp, share, tradesOf } from "../../lib/rebalancer";

const STATUS: Record<string, string> = {
  TRADED: "The index moved all the way to its target.",
  LIMITED_BY_TURNOVER: "The move was shortened to respect the turnover cap, so some stocks are not at their target yet.",
  HELD_BELOW_MIN_TRADE: "The whole rebalance was smaller than the minimum trade, so nothing was traded.",
  AT_TARGET: "The index already sat on its target.",
};

/** What the index bought and sold at this cycle, and how much of the move the turnover cap allowed. */
export function TradesPanel({ detail }: { detail: RebalanceCycleDetail }) {
  const trades = tradesOf(detail.names);
  const buys = trades.filter((t) => t.side === "BUY");
  const sells = trades.filter((t) => t.side === "SELL");
  return (
    <div>
      <p className="text-sm text-ink-2">
        <span className="num font-medium text-ink">{share(detail.turnover)}</span> of the index traded
        {detail.wanted_turnover > detail.turnover + 1e-9 && <> (the target asked for <span className="num">{share(detail.wanted_turnover)}</span>, {share(detail.alpha, 0)} of the way)</>}.
        {" "}{STATUS[detail.status] ?? ""}
      </p>
      {trades.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No trade at this cycle.</p>
      ) : (
        <div className="mt-3 grid gap-4 sm:grid-cols-2">
          {([["Buy", buys, "text-pos"], ["Sell", sells, "text-neg"]] as const).map(([label, list, tone]) => (
            <div key={label}>
              <h3 className="eyebrow">{label} <span className="num">{list.length}</span></h3>
              {list.length === 0 ? <p className="mt-1 text-sm text-muted">None</p> : (
                <ul className="m-0 mt-1 list-none space-y-1 p-0">
                  {list.map((t) => (
                    <li key={t.ticker} className="flex items-baseline justify-between gap-3 text-sm">
                      <b className="num">{t.ticker}</b>
                      <span className={`num ${tone}`}>{pp(t.change)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

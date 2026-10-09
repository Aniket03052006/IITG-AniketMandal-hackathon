import type { RebalanceCycleDetail } from "../../api/types";
import { REASON_HELP, REASON_LABEL, pp, share } from "../../lib/rebalancer";
import { DriverRow } from "./DriverRow";

/** The reports behind one stock's sentiment score. Their contributions add up to the score exactly, so the score is a sum a reader can check. */
export function DriversPanel({ detail, ticker, name }: { detail: RebalanceCycleDetail; ticker: string; name: string }) {
  const n = detail.names.find((x) => x.ticker === ticker);
  const drivers = detail.drivers[ticker] ?? [];
  if (!n) return <p className="text-sm text-muted">Pick a stock to see the reports behind its weight.</p>;
  const listed = drivers.reduce((a, d) => a + d.contribution, 0);
  return (
    <div>
      <p className="text-sm text-ink-2">
        <b className="num">{ticker}</b> ({name}) holds <span className="num font-medium text-ink">{share(n.weight)}</span>, <span className="num">{pp(n.active)}</span> against its benchmark.
        {" "}{REASON_LABEL[n.reason]}: {REASON_HELP[n.reason]}
      </p>
      <p className="mt-2 text-sm text-ink-2">
        Sentiment score <span className="num font-medium text-ink">{n.score >= 0 ? "+" : "−"}{Math.abs(n.score).toFixed(3)}</span> from <span className="num">{n.reports}</span> report{n.reports === 1 ? "" : "s"} by{" "}
        <span className="num">{n.sources}</span> source{n.sources === 1 ? "" : "s"}; each source counts for at most one vote.
      </p>
      {drivers.length === 0 ? (
        <p className="mt-3 text-sm text-muted">No report about this company falls inside the evidence window at this cycle, so it carries no sentiment.</p>
      ) : (
        <>
          <ol className="m-0 mt-3 list-none divide-y divide-rule p-0">
            {drivers.map((d) => <DriverRow key={d.signal_id} d={d} />)}
          </ol>
          <p className="mt-2 text-xs text-muted">
            {n.reports > drivers.length ? `The ${drivers.length} largest of ${n.reports} reports shown (they account for ${listed >= 0 ? "+" : "−"}${Math.abs(listed).toFixed(3)} of the score).` : "All reports shown; the contributions add up to the score."}
          </p>
        </>
      )}
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import type { RebalanceDecisions } from "../../api/types";
import type { RebalancerQuery } from "../../api/client";
import { share, type SeriesSpec } from "../../lib/rebalancer";
import { Stat } from "../ui";
import { AllocationTable } from "./AllocationTable";
import { ApprovalBar } from "./ApprovalBar";
import { DecisionCard } from "./DecisionCard";

const STATUS: Record<string, string> = {
  TRADED: "The index moves all the way to its target.",
  LIMITED_BY_TURNOVER: "The move is shortened to respect the turnover cap, so some stocks are not at their target yet.",
  HELD_BELOW_MIN_TRADE: "The whole rebalance is smaller than the minimum trade, so nothing is traded.",
  AT_TARGET: "The index already sits on its target.",
};

/** A cycle as a proposed rebalance: the numbers, the table, one card per trade with the headlines behind it, and the approval. */
export function DecisionBoard({ proposal, series, q }: { proposal: RebalanceDecisions; series: SeriesSpec[]; q: RebalancerQuery }) {
  const traded = useMemo(() => proposal.decisions.filter((d) => d.side !== "HOLD"), [proposal]);
  const held = useMemo(() => proposal.decisions.filter((d) => d.side === "HOLD"), [proposal]);
  const [accepted, setAccepted] = useState<Set<string>>(() => new Set(traded.map((d) => d.ticker)));
  const [selected, setSelected] = useState<string | null>(null);
  // a different proposal (another cycle, strategy or what-if) starts with every trade included again: a selection never carries over to evidence it was not made on
  useEffect(() => setAccepted(new Set(traded.map((d) => d.ticker))), [proposal.proposal_sha256]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (t: string, on: boolean) => setAccepted((s) => { const n = new Set(s); if (on) n.add(t); else n.delete(t); return n; });
  const pick = (t: string) => {
    setSelected(t);
    document.getElementById(`rb-card-${t}`)?.scrollIntoView({ block: "nearest", behavior: "auto" });
  };
  return (
    <div className="space-y-6">
      <section aria-label="Proposal summary" className="card card-pad grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-5">
        <Stat label="Buys" value={proposal.buys} sub="stocks to add to" />
        <Stat label="Sells" value={proposal.sells} sub="stocks to cut" />
        <Stat label="Held" value={proposal.holds} sub="no trade" />
        <Stat label="Turnover" value={share(proposal.turnover)} sub={proposal.wanted_turnover > proposal.turnover + 1e-9 ? `of ${share(proposal.wanted_turnover)} the rule asked for` : "one-way, of the index"} />
        <Stat label="Est. cost" value={`$${Math.round(proposal.est_cost_usd).toLocaleString("en-US")}`} sub={`${(proposal.est_cost * 1e4).toFixed(2)} bp of a mock $1 bn index`} />
      </section>
      <p className="text-sm text-ink-2">{STATUS[proposal.status] ?? ""} Costs are illustrative: a flat one-way rate on what is traded.</p>
      <AllocationTable rows={proposal.decisions} series={series} selected={selected} onSelect={pick} />
      <ApprovalBar proposal={proposal} accepted={accepted} q={q} />
      <section aria-label="Trade decisions" className="space-y-3">
        <h2 className="text-lg">Why each trade</h2>
        {traded.length === 0 && <p className="text-sm text-muted">No stock trades at this cycle.</p>}
        {traded.map((d) => <DecisionCard key={d.ticker} id={`rb-card-${d.ticker}`} d={d} accepted={accepted.has(d.ticker)} onAccept={(on) => toggle(d.ticker, on)} selectable selected={selected === d.ticker} />)}
        {held.length > 0 && (
          <details className="disclosure">
            <summary>{held.length} stock{held.length === 1 ? "" : "s"} with no trade</summary>
            <div className="mt-2 space-y-3">{held.map((d) => <DecisionCard key={d.ticker} id={`rb-card-${d.ticker}`} d={d} accepted={false} onAccept={() => undefined} selectable={false} selected={selected === d.ticker} />)}</div>
          </details>
        )}
      </section>
    </div>
  );
}

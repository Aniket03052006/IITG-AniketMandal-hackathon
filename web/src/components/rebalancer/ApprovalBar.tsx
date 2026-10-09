import { useState } from "react";
import type { LedgerEntry, RebalanceDecisions } from "../../api/types";
import { useRebalancerDecide } from "../../api/hooks";
import type { RebalancerQuery } from "../../api/client";
import { getAnalyst, setAnalyst } from "../../lib/analyst";
import { dateTime } from "../../lib/format";
import { pp, previewApproval, share, turnoverBetween } from "../../lib/rebalancer";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";

/** Approve or reject a proposed rebalance. Simulated: nothing is sent anywhere and the served index does not change; the decision is a line in the ledger, valid only for this exact proposal. */
export function ApprovalBar({ proposal, accepted, q, onDecided }: { proposal: RebalanceDecisions; accepted: ReadonlySet<string>; q: RebalancerQuery; onDecided?: (e: LedgerEntry) => void }) {
  const decide = useRebalancerDecide();
  const [note, setNote] = useState("");
  const [analyst, setName] = useState(getAnalyst());
  const traded = proposal.decisions.filter((d) => d.side !== "HOLD");
  const all = traded.every((d) => accepted.has(d.ticker));
  const prev = previewApproval(proposal.decisions, proposal.tickers, all ? null : accepted);
  const before = proposal.tickers.map((t) => proposal.decisions.find((d) => d.ticker === t)!.before);
  const turn = turnoverBetween(before, prev.weights);
  const last = proposal.latest_decision;
  const ready = analyst.trim().length > 0 && !prev.problem && traded.length > 0;
  const send = (action: "APPROVE" | "REJECT") => {
    setAnalyst(analyst.trim());
    decide.mutate(
      {
        strategy: proposal.strategy, cycle_index: proposal.index, tilt: q.tilt ?? null, half_life_hours: q.half_life_hours ?? null, max_turnover: q.max_turnover ?? null,
        include_live: q.include_live === true, action, accepted_tickers: action === "APPROVE" && !all ? [...accepted] : null, note: note.trim(), analyst: analyst.trim(), proposal_sha256: proposal.proposal_sha256,
      },
      { onSuccess: (e) => { setNote(""); onDecided?.(e); } },
    );
  };
  return (
    <section aria-label="Approve or reject this rebalance" className="rb-approval">
      <h3 className="m-0 text-base">Approve or reject this rebalance</h3>
      <p className="mt-1 text-sm text-ink-2">
        A simulated decision. Nothing is sent to a broker and the served index does not change; the decision is recorded in the ledger and is valid only for this exact proposal.
      </p>
      {last && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm" role="status">
          <StatusTag tone={last.stale ? "warn" : last.action === "APPROVE" ? "ok" : "demo"}>{last.stale ? "Decided on an earlier version" : last.action === "APPROVE" ? "Approved" : "Rejected"}</StatusTag>
          <span>by <b>{last.analyst}</b> on {dateTime(last.recorded_at)}{last.note ? <>: <q>{last.note}</q></> : null}.</span>
        </p>
      )}
      {traded.length === 0 ? (
        <p className="mt-3 text-sm text-muted">This proposal trades nothing, so there is nothing to approve.</p>
      ) : (
        <>
          <p className="mt-3 text-sm" aria-live="polite">
            Approving <b className="num">{prev.accepted.length}</b> of <b className="num">{traded.length}</b> trades gives a turnover of <b className="num">{share(turn)}</b>
            {prev.rejected.length > 0 && <> (the proposal asked for <span className="num">{share(proposal.turnover)}</span>; {pp(turn - proposal.turnover, 2)})</>}.
          </p>
          {prev.problem && <p className="mt-2 text-sm text-neg" role="alert">{prev.problem}</p>}
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="rb-analyst" className="text-xs text-muted">Your name</label>
              <input id="rb-analyst" className="field mt-1 w-40" value={analyst} maxLength={80} onChange={(e) => setName(e.target.value)} disabled={decide.isPending} />
            </div>
            <div className="min-w-[14rem] flex-1">
              <label htmlFor="rb-note" className="text-xs text-muted">Note (optional)</label>
              <input id="rb-note" className="field mt-1 w-full" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="what you checked, or why you are not following the rule" disabled={decide.isPending} />
            </div>
            <button type="button" className="btn btn-primary" disabled={!ready || decide.isPending} onClick={() => send("APPROVE")}>Approve {all ? "all trades" : `${prev.accepted.length} trades`}</button>
            <button type="button" className="btn" disabled={analyst.trim().length === 0 || decide.isPending} onClick={() => send("REJECT")}>Reject</button>
          </div>
        </>
      )}
      {decide.isSuccess && <p className="mt-2 text-sm text-ink-2" role="status">Recorded in the ledger as entry <span className="num">{decide.data.seq}</span>.</p>}
      {decide.isError && (
        <div className="mt-3">
          <StateNotice tone="warn" what="The decision was not recorded." why={decide.error.message} next={<span className="text-sm">Nothing was changed. Reload the proposal and decide again.</span>} />
        </div>
      )}
    </section>
  );
}

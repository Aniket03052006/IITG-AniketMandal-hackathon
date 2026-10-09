import type { LedgerEntry, LedgerView } from "../../api/types";
import { dateTime } from "../../lib/format";
import { pp, share } from "../../lib/rebalancer";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";

function Allocation({ e }: { e: LedgerEntry }) {
  return (
    <details className="disclosure">
      <summary>Show allocation</summary>
      <div className="scroll-x mt-2">
        <table className="dtable min-w-[28rem]">
          <caption className="sr-only">Weights before, as proposed and as approved, for entry {e.seq}</caption>
          <thead><tr><th scope="col">Stock</th><th scope="col" className="text-right">Before</th><th scope="col" className="text-right">Proposed</th><th scope="col" className="text-right">Approved</th></tr></thead>
          <tbody>
            {e.tickers.map((t, i) => (
              <tr key={t}>
                <th scope="row" className="num">{t}</th>
                <td className="num text-right">{share(e.before[i]!)}</td>
                <td className="num text-right">{share(e.proposed[i]!)}</td>
                <td className="num text-right">{share(e.approved[i]!)}{Math.abs(e.approved[i]! - e.proposed[i]!) > 5e-5 && <span className="text-muted"> ({pp(e.approved[i]! - e.proposed[i]!)})</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

/** Every simulated decision, newest first. A line is a record of what an analyst chose, not an order; a stale one was made on a proposal that has since changed. */
export function LedgerTable({ view }: { view: LedgerView }) {
  return (
    <div className="space-y-4">
      {!view.chain_ok && <StateNotice tone="neg" what="The ledger's hash chain is broken." why={<>Entry <span className="num">{view.broken_at}</span> does not follow from the one before it, so a line was edited or removed after it was written. New entries are refused until this is investigated.</>} />}
      <p className="text-sm text-ink-2">
        <span className="num">{view.total}</span> decision{view.total === 1 ? "" : "s"} ({view.approvals} approved, {view.rejections} rejected). Simulated: nothing here was sent to a broker, and the served index is unaffected.
      </p>
      {view.paper_book && (
        <p className="text-sm text-ink-2">
          Allocation after the latest approval ({view.paper_book.strategy}, cycle {dateTime(view.paper_book.cycle_at)}):{" "}
          <span className="num">{view.paper_book.tickers.map((t, i) => `${t} ${share(view.paper_book!.weights[i]!, 1)}`).join(" · ")}</span>
        </p>
      )}
      {view.entries.length === 0 ? (
        <StateNotice tone="info" what="No decision has been recorded." why="Approve or reject a proposed rebalance on the Decisions tab and it appears here." />
      ) : (
        <div className="scroll-x">
          <table className="dtable min-w-[58rem]">
            <caption className="sr-only">Simulated decisions on proposed rebalances</caption>
            <thead>
              <tr>
                <th scope="col" className="text-right">#</th>
                <th scope="col">Recorded</th>
                <th scope="col">Decision</th>
                <th scope="col">Proposal</th>
                <th scope="col">By</th>
                <th scope="col" className="text-right">Trades</th>
                <th scope="col" className="text-right">Turnover</th>
                <th scope="col" className="text-right">Est. cost</th>
                <th scope="col" className="text-right" title="how far the approved allocation is from the proposed one">Differs from proposal</th>
                <th scope="col">Note</th>
              </tr>
            </thead>
            <tbody>
              {view.entries.map((e) => (
                <tr key={e.id}>
                  <th scope="row" className="num text-right">{e.seq}</th>
                  <td className="num">{dateTime(e.recorded_at)}</td>
                  <td>
                    <StatusTag tone={e.action === "APPROVE" ? "ok" : "demo"}>{e.action === "APPROVE" ? "Approved" : "Rejected"}</StatusTag>
                    {e.stale && <> <StatusTag tone="warn">Proposal changed since</StatusTag></>}
                  </td>
                  <td>{e.strategy} · cycle <span className="num">{e.cycle_index}</span> <span className="text-xs text-muted">({dateTime(e.cycle_at)})</span><Allocation e={e} /></td>
                  <td>{e.analyst}</td>
                  <td className="num text-right">{e.accepted_tickers.length} of {e.accepted_tickers.length + e.rejected_tickers.length}</td>
                  <td className="num text-right">{share(e.turnover)}</td>
                  <td className="num text-right">{(e.est_cost * 1e4).toFixed(2)} bp</td>
                  <td className="num text-right">{share(e.tracking_difference)}</td>
                  <td className="max-w-[18rem] break-words">{e.note || <span className="text-muted">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{view.labels.map((l) => <li key={l}>{l}</li>)}</ul>
    </div>
  );
}

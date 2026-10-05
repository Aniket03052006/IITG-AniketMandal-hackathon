import type { GraphEdge, GraphNode, PropagationGraph } from "../../api/types";
import { money, pct } from "../../lib/format";
import { NODE_KIND_LABEL } from "../../lib/propagation";
import { StateNotice } from "../StateNotice";
import { AdjustedChip } from "./AdjustedChip";
import { BasisChip, StatusChip } from "./StatusChip";

const RELATION: Record<string, string> = {
  EVIDENCED_BY: "is about",
  MEMBER_OF: "is part of",
  ABOUT: "bears on",
  SENSITIVE_TO: "reaches (structural)",
  ASSUMED_TRANSMISSION: "assumed to reach",
  HELD_BY: "held in",
  DRIVES: "drives",
};

function Node({ n }: { n: GraphNode }) {
  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2">
      <span className="text-xs text-muted">{NODE_KIND_LABEL[n.kind] ?? n.kind}</span>
      <span className="font-medium text-ink">{n.label}</span>
      {n.share != null && n.kind !== "PORTFOLIO" && n.kind !== "EVENT" && <span className="num text-xs text-muted">{pct(n.share)} of the book</span>}
    </span>
  );
}

function EdgeRow({ e, byId }: { e: GraphEdge; byId: Map<string, GraphNode> }) {
  const a = byId.get(e.source);
  const b = byId.get(e.target);
  if (!a || !b) return null;
  return (
    <li className="rounded-md border border-rule bg-paper-2 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <Node n={a} />
        <span aria-hidden="true" className="text-muted">→</span>
        <span className="sr-only">{RELATION[e.relationship] ?? e.relationship}</span>
        <Node n={b} />
        <span className="ml-auto flex items-center gap-2">
          {e.weight != null && <span className="num text-xs text-muted" title="Positive hurts the target, negative benefits it">weight {e.weight > 0 ? "+" : ""}{e.weight.toFixed(2)}</span>}
          <StatusChip status={e.status} />
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        <span className="font-medium text-ink-2">{RELATION[e.relationship] ?? e.relationship}.</span> {e.basis} <span className="num opacity-70">[{e.rule_id}]</span>
      </p>
    </li>
  );
}

/** Event → subject → risk factor → portfolio → holdings, every edge with its rule, its evidence or assumption, and whether it is observed or assumed. A mapping, not a causal model. */
export function PropagationChain({ g }: { g: PropagationGraph }) {
  const byId = new Map(g.nodes.map((n) => [n.id, n]));
  if (g.availability === "ABSTAINED") {
    return (
      <div className="mt-6 border-t border-rule pt-5" aria-label="Exposure chain">
        <p className="eyebrow">My exposure</p>
        <div className="mt-2 max-w-[64ch]">
          <StateNotice tone="warn" what="No defensible mapping to the portfolio" why={g.reason ?? "The text names nothing the event could attach to."} next="EventShock does not guess what an event is about." />
        </div>
      </div>
    );
  }
  const edges = g.edges.filter((e) => e.relationship !== "HELD_BY" || e.target === "portfolio");
  const flow = edges.filter((e) => e.target !== "portfolio" && !e.target.startsWith("pos:"));
  const held = edges.filter((e) => e.target === "portfolio");
  return (
    <div className="mt-6 border-t border-rule pt-5" aria-label="Exposure chain">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">My exposure: event → risk factor → holdings</p>
        <AdjustedChip notice={g.adjustments} />
      </div>
      <p className="mt-1 max-w-[66ch] text-sm text-muted">{g.labels.join(" ")}</p>
      {g.reason && <p className="mt-2 max-w-[66ch] text-sm text-ink-2">{g.reason}</p>}
      <dl className="mt-3 grid max-w-[52rem] grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <div><dt className="text-xs text-muted">Reached</dt><dd className="num">{pct(g.reached_share)}</dd></div>
        <div><dt className="text-xs text-muted">Direct</dt><dd className="num">{pct(g.direct_share)}</dd></div>
        <div><dt className="text-xs text-muted">Evidenced</dt><dd className="num">{pct(g.evidenced_share)}</dd></div>
        <div><dt className="text-xs text-muted">Only assumed</dt><dd className="num">{pct(g.assumed_share)}</dd></div>
      </dl>
      {g.active_factors.length > 0 && (
        <ul className="mt-4 flex flex-wrap gap-2" aria-label="Risk factors in play">
          {g.active_factors.map((f) => (
            <li key={f.id} className="rounded-md border border-rule px-2.5 py-1.5 text-sm" title={f.evidence.join("; ")}>
              <span className="font-medium">{f.label}</span> <StatusChip status={f.status} className="ml-1" />
              {f.note && <span className="mt-0.5 block text-xs text-muted">{f.note}</span>}
            </li>
          ))}
        </ul>
      )}
      <ol className="mt-4 grid max-w-[60rem] gap-2" aria-label="Edges from the event to the portfolio">
        {flow.map((e) => <EdgeRow key={`${e.source}>${e.target}>${e.rule_id}`} e={e} byId={byId} />)}
      </ol>
      <details className="disclosure mt-4" open={g.reached.length > 0 && g.reached.length <= 8}>
        <summary>{g.reached.length} holdings reached ({money(g.reached_value)})</summary>
        <table className="mt-3 w-full max-w-[56rem] text-sm">
          <caption className="sr-only">Holdings the event reaches</caption>
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="pb-1 pr-3 font-medium">Holding</th>
              <th scope="col" className="pb-1 pr-3 font-medium">Class</th>
              <th scope="col" className="pb-1 pr-3 font-medium">Sector / industry</th>
              <th scope="col" className="pb-1 pr-3 text-right font-medium">Value</th>
              <th scope="col" className="pb-1 font-medium">Reached</th>
            </tr>
          </thead>
          <tbody>
            {g.reached.slice(0, 40).map((h) => (
              <tr key={h.asset_id} className="border-t border-rule align-top">
                <th scope="row" className="py-1.5 pr-3 text-left font-normal">{h.name}</th>
                <td className="py-1.5 pr-3 text-muted">{h.asset_type.toLowerCase()}</td>
                <td className="py-1.5 pr-3 text-muted">{h.sector}{h.industry ? ` · ${h.industry}` : ""}</td>
                <td className="num py-1.5 pr-3 text-right">{money(h.market_value)}</td>
                <td className="py-1.5"><BasisChip basis={h.basis} /> <span className="text-xs text-muted">{h.routes.slice(0, 2).join(", ")}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {g.reached.length > 40 && <p className="mt-2 text-xs text-muted">The 40 largest of {g.reached.length}.</p>}
      </details>
      {held.length === 0 && g.reached.length === 0 && <p className="mt-3 text-sm text-muted">The book holds nothing this mapping reaches.</p>}
      {g.not_reached.length > 0 && (
        <details className="disclosure mt-3">
          <summary>{g.not_reached.length} mapped target{g.not_reached.length > 1 ? "s" : ""} the book holds nothing in</summary>
          <ul className="mt-2 list-disc pl-5 text-sm text-muted">{g.not_reached.map((x) => <li key={x}>{x}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

import type { PipelineReport } from "../../api/types";
import { stageKind } from "../../lib/provenance";

const n = (v: number) => v.toLocaleString("en-US");

/** Source -> ... -> Stress as one picture, with the few real numbers each stage can state. Detail (quarantine, provenance) sits behind expanders. */
export function PipelineFlow({ r }: { r: PipelineReport }) {
  const c = r.counts;
  const o = r.stage_origins;
  const kind = (k: string) => (stageKind(o[k]) === "model" ? "trained model" : "placeholder rules");
  const nodes = [
    { k: "Source", a: `${n(c.records_read)} records`, b: `${r.sources.length} sources, licences recorded` },
    { k: "Validate", a: `${n(c.quarantined)} quarantined`, b: "each with a reason code" },
    { k: "Deduplicate", a: `${n(c.exact_duplicates_folded)} folded`, b: `${n(c.syndicated)} syndicated · ${n(c.near_duplicates + c.same_event)} merged stories` },
    { k: "Entity resolution", a: `${n(c.entity_resolved)} linked`, b: `${n(c.entity_unknown)} unresolved · ${n(c.rejected_ambiguous_mentions)} refused` },
    { k: "NLP", a: `${n(c.signals)} signals`, b: `sentiment: ${kind("sentiment")} · event: ${kind("event")}` },
    { k: "Impact", a: kind("impact"), b: "experimental where a model can score" },
    { k: "Evidence", a: "novelty, coverage", b: "comparable events, filings" },
    { k: "Stress", a: "scenario mapping", b: "deterministic engine" },
  ];
  return (
    <ol className="pflow" aria-label="Pipeline stages in order">
      {nodes.map((x, i) => (
        <li key={x.k} className="pflow-node" style={{ ["--i" as string]: i }}>
          <p className="pflow-k">
            <span className="chain-n num">{i + 1}</span>
            {x.k}
          </p>
          <p className="mt-1 font-medium text-ink">{x.a}</p>
          <p className="text-xs text-muted">{x.b}</p>
        </li>
      ))}
    </ol>
  );
}

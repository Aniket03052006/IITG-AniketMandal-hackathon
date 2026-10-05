import type { Origin, ProvenanceLine } from "../../api/types";
import { OriginChip } from "./OriginChip";

const ORDER: Origin[] = ["AI", "HYBRID", "DATA", "RULES", "RETRIEVED", "ASSUMPTION"];

/** Which parts of the result are AI, data, rules, hybrid or an assumption: the counts at a glance, the full list one click away. */
export function ProvenanceStrip({ lines }: { lines: ProvenanceLine[] }) {
  const counts = ORDER.map((o) => [o, lines.filter((l) => l.origin === o).length] as const).filter(([, n]) => n > 0);
  return (
    <details className="disclosure">
      <summary>Where each part comes from</summary>
      <div className="mt-3 space-y-3">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
          {counts.map(([o, n]) => (
            <span key={o} className="inline-flex items-center gap-1.5">
              <OriginChip origin={o} /> {n}
            </span>
          ))}
        </p>
        <ul className="divide-y divide-rule border-y border-rule" aria-label="Provenance of each part">
          {lines.map((l) => (
            <li key={l.part} className="grid gap-x-4 gap-y-1 py-2 sm:grid-cols-[minmax(0,13rem)_auto_minmax(0,1fr)] sm:items-start">
              <span className="text-sm font-medium text-ink">{l.part}</span>
              <span>
                <OriginChip origin={l.origin} />
              </span>
              <span className="text-sm text-ink-2">{l.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

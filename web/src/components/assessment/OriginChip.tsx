import clsx from "clsx";
import type { Origin } from "../../api/types";
import { Database, History, Inputs, Model, Sigma, Wrench } from "../icons";

export const ORIGIN_META: Record<Origin, { label: string; says: string; Icon: typeof Model; cls: string }> = {
  AI: { label: "AI", says: "A language model's (or a trained classifier's) reading of the text.", Icon: Model, cls: "origin-ai" },
  DATA: { label: "Data", says: "An observation: market data, timestamps, source metadata.", Icon: Database, cls: "origin-data" },
  RULES: { label: "Rules", says: "Deterministic logic: cue phrases, comparison with earlier reports, exposure, scenario mapping, portfolio arithmetic.", Icon: Sigma, cls: "origin-rules" },
  HYBRID: { label: "Hybrid", says: "More than one of the above combined: for example a rules baseline moved by a bounded AI adjustment.", Icon: Inputs, cls: "origin-hybrid" },
  RETRIEVED: { label: "Retrieved", says: "A past report found by similarity, with what the market did after it: precedent about other events, never a reading of this one.", Icon: History, cls: "origin-retrieved" },
  ASSUMPTION: { label: "Assumption", says: "A configured judgement: a matrix anchor, a multiplier, a scenario shock. Documented, not fitted.", Icon: Wrench, cls: "origin-assumption" },
};

/** Where one part of the result comes from. Icon + word + its own outline: never colour alone. */
export function OriginChip({ origin, className }: { origin: Origin; className?: string }) {
  const m = ORIGIN_META[origin];
  return (
    <span className={clsx("origin", m.cls, className)} title={m.says}>
      <m.Icon size={11} />
      {m.label}
    </span>
  );
}

export function OriginLegend({ className }: { className?: string }) {
  return (
    <ul className={clsx("flex flex-wrap items-center gap-x-3 gap-y-1.5", className)} aria-label="What the origin labels mean">
      {(Object.keys(ORIGIN_META) as Origin[]).map((o) => (
        <li key={o} className="flex items-center gap-1.5 text-xs text-muted">
          <OriginChip origin={o} />
          <span className="hidden lg:inline">{ORIGIN_META[o].says.split(":")[0]!.split(".")[0]}</span>
        </li>
      ))}
    </ul>
  );
}

import clsx from "clsx";
import { History, Model, Realised, Scenario } from "./icons";

/**
 * What KIND of number is this? The four never blur into one another:
 *   model       a prediction a model made from information available at event time
 *   historical  an observation of what already happened (aggregated; never an individual event we could not verify)
 *   scenario    an assumption someone chose, run through a deterministic engine: a simulation, not a forecast
 *   realised    what the market actually did afterwards (known only after the fact; never an input)
 * Each is drawn with its own icon, border/fill pattern AND a word, so colour is never the only signal.
 */
export type NumberKind = "model" | "historical" | "scenario" | "realised";

export const KIND_META: Record<NumberKind, { label: string; says: string; Icon: typeof Model }> = {
  model: { label: "Model prediction", says: "Estimated by a model from what was known at event time.", Icon: Model },
  historical: { label: "Historical observation", says: "What already happened in past data; an aggregate, not a forecast.", Icon: History },
  scenario: { label: "Scenario assumption", says: "A chosen shock run through a deterministic engine: a simulation, not a prediction.", Icon: Scenario },
  realised: { label: "Realised outcome", says: "What the market actually did afterwards. Known only after the fact; never a model input.", Icon: Realised },
};

export function KindBadge({ kind, label, className }: { kind: NumberKind; label?: string; className?: string }) {
  const { label: text, says, Icon } = KIND_META[kind];
  return (
    <span className={clsx("kind", `kind-${kind}`, className)} title={says}>
      <Icon size={12} />
      {label ?? text}
    </span>
  );
}

/** The four kinds with their one-line meaning, for a legend. */
export function KindLegend({ className }: { className?: string }) {
  return (
    <dl className={clsx("grid gap-x-6 gap-y-3 sm:grid-cols-2", className)}>
      {(Object.keys(KIND_META) as NumberKind[]).map((k) => (
        <div key={k} className="min-w-0">
          <dt>
            <KindBadge kind={k} />
          </dt>
          <dd className="mt-1 text-sm text-muted">{KIND_META[k].says}</dd>
        </div>
      ))}
    </dl>
  );
}

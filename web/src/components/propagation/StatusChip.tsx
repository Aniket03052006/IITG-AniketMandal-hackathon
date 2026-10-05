import clsx from "clsx";
import type { MappingBasis, PropagationStatus } from "../../api/types";
import { BASIS_LABEL, BASIS_SAYS, STATUS_LABEL, STATUS_SAYS } from "../../lib/propagation";
import { History, Scenario, Wrench } from "../icons";

const CLS: Record<PropagationStatus, string> = { OBSERVED: "kind-historical", SCENARIO_ASSUMPTION: "kind-scenario", USER_ASSUMPTION: "kind-prior" };
const ICON = { OBSERVED: History, SCENARIO_ASSUMPTION: Scenario, USER_ASSUMPTION: Wrench } as const;

/** Observed vs assumed, drawn with an icon, a border pattern AND a word: colour is never the only signal. */
export function StatusChip({ status, className }: { status: PropagationStatus; className?: string }) {
  const Icon = ICON[status];
  return (
    <span className={clsx("kind", CLS[status], className)} title={STATUS_SAYS[status]}>
      <Icon size={12} />
      {STATUS_LABEL[status]}
    </span>
  );
}

/** How a holding is reached (direct, evidenced, assumed). */
export function BasisChip({ basis, className }: { basis: MappingBasis; className?: string }) {
  return (
    <span className={clsx("kind", basis === "ASSUMPTION_ONLY" ? "kind-scenario" : basis === "NONE" ? "kind-state" : "kind-historical", className)} title={BASIS_SAYS[basis]}>
      {BASIS_LABEL[basis]}
    </span>
  );
}

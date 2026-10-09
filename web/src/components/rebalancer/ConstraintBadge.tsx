import type { ConstraintEffect } from "../../api/types";
import { CONSTRAINT_HELP, CONSTRAINT_LABEL, isRiskRule, pp } from "../../lib/rebalancer";
import { StatusTag } from "../ui";

/** The rule that held a stock back and by how much. The word and the signed number carry the meaning; the tone only separates a risk rule from the pacing of the trade. */
export function ConstraintBadge({ effect }: { effect: ConstraintEffect }) {
  return (
    <span title={`${CONSTRAINT_HELP[effect.code]} Effect on this stock's weight: ${pp(effect.effect)}.`}>
      <StatusTag tone={isRiskRule(effect.code) ? "warn" : "demo"}>
        <span>{CONSTRAINT_LABEL[effect.code]}</span>
        <span className="num">{pp(effect.effect)}</span>
      </StatusTag>
    </span>
  );
}

import clsx from "clsx";
import { ASSESSMENT_KIND } from "../../lib/assessment";
import { History, Model, Realised, Scenario, Sigma } from "../icons";

const STYLE: Record<string, { cls: string; Icon: typeof Model }> = {
  SOURCE: { cls: "kind-source", Icon: History },
  EXTRACTION: { cls: "kind-ai", Icon: Model },
  JUDGEMENT_PRIOR: { cls: "kind-prior", Icon: Sigma },
  MARKET_STATE: { cls: "kind-state", Icon: History },
  MODEL_REFERENCE: { cls: "kind-model", Icon: Model },
  SCENARIO_ASSUMPTION: { cls: "kind-scenario", Icon: Scenario },
  REALISED: { cls: "kind-realised", Icon: Realised },
};

/** What KIND of statement this is (source text, AI reading, judgement prior, market state, reference model, assumption, realised). Icon + outline + a word: never colour alone. */
export function AssessmentKind({ kind, className }: { kind: string; className?: string }) {
  const meta = ASSESSMENT_KIND[kind] ?? { label: kind, says: "" };
  const { cls, Icon } = STYLE[kind] ?? STYLE.SOURCE!;
  return (
    <span className={clsx("kind", cls, className)} title={meta.says}>
      <Icon size={12} />
      {meta.label}
    </span>
  );
}

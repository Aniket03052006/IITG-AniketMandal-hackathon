import type { ImpactLifecycle, Meta, RiskSignal, SignalSummary } from "../api/types";

/** What the UI calls the three states an impact number can be in. Never collapse them: an unvalidated number must not look authoritative. */
export type ImpactKind = "placeholder" | "experimental" | "validated";

export const KIND_LABEL: Record<ImpactKind, string> = {
  placeholder: "Placeholder rule",
  experimental: "Experimental model",
  validated: "Validated model",
};

/** TRAINED and CALIBRATED are experimental (a bar was missed or not evaluated); only PRODUCTION (every pre-registered check passed) is validated. */
export function lifecycleKind(lifecycle: ImpactLifecycle | string | null | undefined): ImpactKind {
  if (lifecycle === "PRODUCTION") return "validated";
  if (lifecycle === "TRAINED" || lifecycle === "CALIBRATED") return "experimental";
  return "placeholder";
}

export const LIFECYCLE_STEPS: { id: ImpactLifecycle; label: string; says: string }[] = [
  { id: "NOT_AVAILABLE", label: "Not available", says: "No model artifact: the placeholder rule is all there is." },
  { id: "DATASET", label: "Dataset", says: "A leak-checked dataset exists; nothing is fitted." },
  { id: "BASELINE", label: "Baseline", says: "Only baselines exist, or no candidate beat them." },
  { id: "TRAINED", label: "Trained", says: "Fitted and evaluated on later periods; not calibrated." },
  { id: "CALIBRATED", label: "Calibrated", says: "Score and uncertainty calibrated; an acceptance check was missed or not evaluable." },
  { id: "PRODUCTION", label: "Production", says: "Every pre-registered acceptance check passed." },
];

type WithImpact = Pick<RiskSignal, "provenance" | "impact">;

/** The kind of THIS signal's impact: per signal, because a model scores only what it can and the rest keep the labelled rule. */
export function impactKind(s: WithImpact): ImpactKind {
  return s.provenance?.impact ? lifecycleKind(s.provenance.impact.lifecycle) : "placeholder";
}

export function summaryKind(s: Pick<SignalSummary, "impact_origin" | "impact_lifecycle">): ImpactKind {
  return s.impact_origin === "MODEL" ? lifecycleKind(s.impact_lifecycle) : "placeholder";
}

/** Whether the running app has a trained impact model that scores anything (from /api/meta). */
export const impactIsModel = (meta: Meta | undefined): boolean => meta?.impact?.mode === "MODEL";

/** "experimental" / "validated" / "experimental and validated" for the scopes the app serves; null when there is no model. */
export function servedKinds(meta: Meta | undefined): ImpactKind[] {
  const imp = meta?.impact;
  if (!imp || imp.mode !== "MODEL") return [];
  return [...new Set(imp.served_scopes.map((s) => lifecycleKind(imp.scopes[s])))];
}

export { sigma } from "./format";

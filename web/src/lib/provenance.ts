import type { Meta, RiskSignal } from "../api/types";

/** Short label for the data profile the API is serving. */
export function profileLabel(meta: Meta | undefined): string {
  if (!meta) return "Connecting…";
  const mode = meta.mode === "REPLAY" ? "Replay" : "Live";
  return `${mode} · ${meta.profile === "replay" ? "real sources" : "demo fixtures"}`;
}

/** One-sentence honesty note about what the signals are. */
export function profileNote(meta: Meta): string {
  return meta.profile === "replay"
    ? "Documents are real, replayed from a frozen snapshot. Sentiment, event type and impact are placeholder rules. The stress engine is computed."
    : "Signals are hand-authored fixtures. The stress engine is computed.";
}

export function originLabel(origin: string): string {
  switch (origin) {
    case "DEMO_FIXTURE":
      return "Demo fixture (hand-authored)";
    case "REAL_SOURCE_PLACEHOLDER_NLP":
      return "Real source · placeholder NLP";
    default:
      return "Model output";
  }
}

export const isPlaceholder = (s: RiskSignal): boolean => (s.model_versions.impact ?? "").startsWith("placeholder");

const ORIGIN_NOTE: Record<string, string> = {
  SOURCE: "Publisher time",
  SOURCE_DATE_ONLY: "Publisher date (no time of day)",
  GDELT_FIRST_SEEN: "When GDELT first saw the page",
  SYNTHETIC_REPLAY_CLOCK: "Assigned by replay (the source has no time)",
};
export const timestampNote = (o: string): string => ORIGIN_NOTE[o] ?? o;

const RULE_NOTE: Record<string, string> = {
  CASHTAG: "Cashtag / exchange-qualified ticker",
  LEGAL_NAME: "Legal company name",
  ALIAS: "Known alias",
  BARE_TICKER: "Uppercase ticker in text",
  WEAK_ALIAS: "Ambiguous name with finance context",
  FUZZY: "Close spelling match",
  NONE: "No company mentioned",
  BELOW_THRESHOLD: "Confidence too low to link",
};
export const ruleNote = (r: string): string => RULE_NOTE[r] ?? r;

const RELATION_NOTE: Record<string, string> = {
  SYNDICATED: "Same text, other outlet",
  NEAR_DUPLICATE: "Near-identical wording",
  SAME_EVENT: "Same story, other report",
  EXACT_DUPLICATE: "Exact duplicate",
};
export const relationNote = (r: string): string => RELATION_NOTE[r] ?? r;

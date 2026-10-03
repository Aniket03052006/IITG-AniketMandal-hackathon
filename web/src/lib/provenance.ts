import type { Meta, RiskSignal } from "../api/types";
import { impactIsModel, servedKinds } from "./impact";

/** Short label for the data profile the API is serving. */
export function profileLabel(meta: Meta | undefined): string {
  if (!meta) return "Connecting…";
  const mode = meta.mode === "REPLAY" ? "Replay" : "Live";
  return `${mode} · ${meta.profile === "replay" ? "real sources" : "demo fixtures"}`;
}

export type StageKind = "model" | "source-label" | "placeholder";

/** What produced a stage. Accepts a signal's StageOrigin ("MODEL") or the pipeline report's text ("MODEL (tfidf-lr-v1, …)"). */
export function stageKind(origin: string | undefined): StageKind {
  if (origin?.startsWith("MODEL")) return "model";
  if (origin === "SOURCE_LABEL") return "source-label";
  return "placeholder";
}

/** Whether the sentiment stage of the replay run is a trained model, from the pipeline report's stage_origins. */
export const sentimentIsModel = (meta: Meta | undefined): boolean => stageKind(meta?.replay?.stage_origins?.sentiment) === "model";

/** Whether the event stage of the replay run is a trained model, from the pipeline report's stage_origins. */
export const eventIsModel = (meta: Meta | undefined): boolean => stageKind(meta?.replay?.stage_origins?.event) === "model";

/** The impact clause of the profile note, from what the running app says it serves (never hard-coded). */
function impactClause(meta: Meta): string {
  if (!impactIsModel(meta)) return "impact is a placeholder rule";
  const kinds = servedKinds(meta).join(" / ");
  return `impact is a trained model (${kinds}) where it can score a signal, and a labelled placeholder rule elsewhere`;
}

/** One-sentence honesty note about what the signals are. */
export function profileNote(meta: Meta): string {
  if (meta.profile !== "replay") return "Signals are hand-authored fixtures. The stress engine is computed.";
  const sent = sentimentIsModel(meta);
  const event = eventIsModel(meta);
  const base = "Documents are real, replayed from a frozen snapshot.";
  if (sent && event) {
    return `${base} Sentiment and event type are trained models (event type can say “not an event” or “uncertain”); ${impactClause(meta)}. The stress engine is computed.`;
  }
  if (sent) return `${base} Sentiment is a trained model; event type and impact are placeholder rules. The stress engine is computed.`;
  return `${base} Sentiment, event type and impact are placeholder rules. The stress engine is computed.`;
}

/** "sentiment" / "sentiment and event" for the NLP stages a signal's own provenance says are trained models. */
function trainedStages(stageOrigins?: Record<string, string>): string {
  const names = (["sentiment", "event", "impact"] as const).filter((k) => stageKind(stageOrigins?.[k]) === "model");
  if (!names.length) return "models";
  return names.length > 2 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names.join(" and ");
}

export function originLabel(origin: string, stageOrigins?: Record<string, string>): string {
  switch (origin) {
    case "DEMO_FIXTURE":
      return "Demo fixture (hand-authored)";
    case "REAL_SOURCE_PLACEHOLDER_NLP":
      return "Real source · placeholder NLP";
    case "REAL_SOURCE_MIXED_NLP": {
      const trained = trainedStages(stageOrigins);
      const placeholders = (["sentiment", "event", "impact"] as const).filter((k) => stageKind(stageOrigins?.[k]) !== "model").map(stageName);
      return `Real source · trained ${trained}${stageOrigins && placeholders.length ? `, placeholder ${placeholders.join(" and ").toLowerCase()}` : ""}`;
    }
    default:
      return "Model output";
  }
}

/** Short chip text for a signal's data origin. */
export function originChip(origin: string, stageOrigins?: Record<string, string>): string {
  switch (origin) {
    case "DEMO_FIXTURE":
      return "Demo fixture";
    case "REAL_SOURCE_MIXED_NLP":
      return `Real source · trained ${trainedStages(stageOrigins)}`;
    default:
      return "Real source · placeholder NLP";
  }
}

const STAGE_NAME: Record<string, string> = { sentiment: "Sentiment", event: "Event type", impact: "Impact" };
const KIND_TEXT: Record<StageKind, string> = { model: "Trained model", "source-label": "Source label", placeholder: "Placeholder rules" };
export const stageName = (stage: string): string => STAGE_NAME[stage] ?? stage;
export const stageKindText = (origin: string | undefined): string => KIND_TEXT[stageKind(origin)];

/** True when THIS signal's impact came from the placeholder rule (read from its own stage origin, not from a version string). */
export const isPlaceholder = (s: RiskSignal): boolean => stageKind(s.provenance?.stage_origins.impact) !== "model";

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

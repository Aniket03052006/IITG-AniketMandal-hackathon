import type { ReasonKind } from "../api/types";

/** The four kinds of statement an explanation distinguishes, plus an external market observation. Each has its own word, never colour alone. */
export const REASON_KIND: Record<ReasonKind, { label: string; says: string; badge: "model" | "historical" | "scenario" | null }> = {
  MODEL_OUTPUT: { label: "Model output", says: "EventShock's own reading or scorecard. A triage, not outcome-calibrated.", badge: "model" },
  PRODUCT_RULE: { label: "Product rule", says: "A deterministic rule applied to counted facts or to the engine's arithmetic. No model.", badge: null },
  SCENARIO_ASSUMPTION: { label: "Scenario assumption", says: "A hypothetical shock or configured edge. A simulation, never a prediction.", badge: "scenario" },
  HISTORICAL_OBSERVATION: { label: "Historical observation", says: "What already happened in past data. An aggregate, not a forecast.", badge: "historical" },
  EXTERNAL_MARKET_OBSERVATION: { label: "External market observation", says: "What an independent market is pricing. Never an input to the risk score.", badge: null },
};

export const KIND_ORDER: ReasonKind[] = ["PRODUCT_RULE", "MODEL_OUTPUT", "SCENARIO_ASSUMPTION", "HISTORICAL_OBSERVATION", "EXTERNAL_MARKET_OBSERVATION"];

export const SUBJECT_TITLE: Record<string, string> = {
  PRIORITY: "Why this priority?",
  VISIBILITY: "Why am I seeing this?",
  CHANGE: "Why was this flagged as changed?",
  STRESS: "Why this stress?",
  LAB: "Why this result?",
  REVERSE: "Why these shocks?",
  MARKET: "Why this market?",
};

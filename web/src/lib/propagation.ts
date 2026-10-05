import type { MappingBasis, PropagationStatus } from "../api/types";

/** Plain-language labels for the propagation side-car. Pure: no data, so they can be tested and reused. */
export const STATUS_LABEL: Record<PropagationStatus, string> = {
  OBSERVED: "Observed",
  SCENARIO_ASSUMPTION: "Scenario assumption",
  USER_ASSUMPTION: "Your assumption",
};

export const STATUS_SAYS: Record<PropagationStatus, string> = {
  OBSERVED: "A holding, a formula the stress engine applies to the holding's own attributes, a quoted phrase, or a ticker's industry: a fact, not a judgement.",
  SCENARIO_ASSUMPTION: "A judgement prior in configs/propagation.yaml (a transmission edge or a shock size). Not measured, not validated.",
  USER_ASSUMPTION: "A value you adjusted or added. It changes what EventShock computes; it is your assumption, not validated.",
};

export const BASIS_LABEL: Record<MappingBasis, string> = {
  DIRECT_FACT: "Direct holding",
  EVIDENCED_SCOPE: "Evidenced scope",
  ASSUMPTION_ONLY: "Assumption only",
  NONE: "Not reached",
};

export const BASIS_SAYS: Record<MappingBasis, string> = {
  DIRECT_FACT: "The book holds the issuer the event names.",
  EVIDENCED_SCOPE: "A sector, industry or region the text or the entity master names, or a holding's structural sensitivity to a factor the text is about.",
  ASSUMPTION_ONLY: "Only configured transmission edges reach it.",
  NONE: "Nothing reaches the book.",
};

export const LEVEL_LABEL: Record<string, string> = {
  CRITICAL: "Critical",
  HIGH: "High",
  MEDIUM: "Medium",
  LOW: "Low",
  NONE: "Not relevant",
  UNDETERMINED: "Cannot be stated",
};

export type LevelTone = "neg" | "warn" | "demo" | "ok";
export const levelTone = (level: string): LevelTone => (level === "CRITICAL" ? "neg" : level === "HIGH" || level === "UNDETERMINED" ? "warn" : "demo");

export const NODE_KIND_LABEL: Record<string, string> = {
  EVENT: "Event",
  SCOPE: "Subject",
  SECTOR: "Sector",
  INDUSTRY: "Industry",
  GEOGRAPHY: "Geography",
  RISK_FACTOR: "Risk factor",
  ASSET_CLASS: "Asset class",
  PORTFOLIO: "Portfolio",
  POSITION: "Position",
  STRESS_DRIVER: "Stress driver",
};

export const SOURCE_LABEL: Record<string, string> = { CATALOG_BASE: "Catalog base", PROPAGATED: "Propagated", USER: "Your size" };

/** Adjustment groups, in the order they are shown. */
export const GROUPS: { id: string; label: string; blurb: string }[] = [
  { id: "scenario", label: "Scenarios", blurb: "When a scenario is generated and how big the propagated shocks are." },
  { id: "relevance", label: "Relevance", blurb: "How exposure and severity become a level, and what counts as concentration." },
  { id: "mapping", label: "Mapping", blurb: "Which risk factors reach which sectors and asset classes, and how strongly." },
  { id: "intelligence", label: "Event intelligence", blurb: "The priors behind scope, grouping, evidence, novelty, velocity and lifecycle." },
];

export const DIMENSION_ORDER = ["driver", "issuer", "sector", "industry", "market_factor", "risk_factor", "asset_class", "position"];

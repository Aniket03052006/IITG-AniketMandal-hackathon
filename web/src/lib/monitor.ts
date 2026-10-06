import type { ChangeType, MemoryItem } from "../api/types";

export const CHANGE_LABEL: Record<ChangeType, string> = {
  NEW_EVENT: "New event",
  EVENT_UPDATED: "Updated",
  EVENT_ESCALATED: "Escalated",
  EVENT_DE_ESCALATED: "Easing",
  EVIDENCE_STRENGTHENED: "Evidence stronger",
  EVIDENCE_WEAKENED: "Evidence weaker",
  CONFLICT_APPEARED: "Conflict appeared",
  CONFLICT_RESOLVED: "Conflict resolved",
  PORTFOLIO_EXPOSURE_CHANGED: "Exposure changed",
  STRESS_CHANGED: "Stress changed",
  LIFECYCLE_CHANGED: "Lifecycle changed",
};

/** Every change type, in the order the backend lists them (a fixed order, so the filter chips never move). */
export const CHANGE_TYPES = Object.keys(CHANGE_LABEL) as ChangeType[];

export const CHANGE_TONE: Record<ChangeType, "demo" | "warn" | "ok" | "neg"> = {
  NEW_EVENT: "demo",
  EVENT_UPDATED: "demo",
  EVENT_ESCALATED: "neg",
  EVENT_DE_ESCALATED: "ok",
  EVIDENCE_STRENGTHENED: "ok",
  EVIDENCE_WEAKENED: "warn",
  CONFLICT_APPEARED: "warn",
  CONFLICT_RESOLVED: "ok",
  PORTFOLIO_EXPOSURE_CHANGED: "warn",
  STRESS_CHANGED: "warn",
  LIFECYCLE_CHANGED: "demo",
};

export const CHANGE_BLURB: Record<ChangeType, string> = {
  NEW_EVENT: "The event reached the tracking floor for the first time.",
  EVENT_UPDATED: "A new independent source or report cluster joined the event.",
  EVENT_ESCALATED: "Severity rose, or a report describes the event widening or worsening.",
  EVENT_DE_ESCALATED: "Severity fell, or reports describe the event easing or resolved.",
  EVIDENCE_STRENGTHENED: "More independent corroboration: the evidence tier went up.",
  EVIDENCE_WEAKENED: "The evidence tier went down.",
  CONFLICT_APPEARED: "Reports now contradict each other on a tracked claim.",
  CONFLICT_RESOLVED: "The contradiction between reports is no longer open.",
  PORTFOLIO_EXPOSURE_CHANGED: "How much of the book the event reaches changed.",
  STRESS_CHANGED: "The modeled scenario P&L moved: a simulation, not a forecast.",
  LIFECYCLE_CHANGED: "The event moved to another stage of its life.",
};

export const UPDATE_LABEL: Record<string, string> = {
  NEW_EVENT: "New event",
  CONTINUATION: "Continuation",
  UPDATE: "Update",
  ESCALATION: "Escalation",
  DE_ESCALATION: "De-escalation",
  RESOLUTION: "Resolution",
};

export const UPDATE_TONE: Record<string, "demo" | "warn" | "ok" | "neg"> = {
  NEW_EVENT: "demo",
  CONTINUATION: "demo",
  UPDATE: "ok",
  ESCALATION: "neg",
  DE_ESCALATION: "ok",
  RESOLUTION: "ok",
};

/** The kinds of statement a timeline mixes. They are never blurred: each carries its own word (colour is never the only signal). */
export const OBSERVATION_LABEL: Record<string, string> = {
  SOURCE_EVENT: "Source report",
  EVENTSHOCK_ASSESSMENT: "EventShock assessment",
  EXTERNAL_MARKET_OBSERVATION: "External market observation",
  SCENARIO_ASSUMPTION: "Scenario assumption",
  HISTORICAL_OBSERVATION: "Historical observation",
  REALISED_OUTCOME: "Realised outcome",
  PRODUCT_RULE: "Product rule",
};

export const OBSERVATION_KIND: Record<string, "model" | "historical" | "scenario" | "realised" | null> = {
  SOURCE_EVENT: null,
  EVENTSHOCK_ASSESSMENT: "model",
  EXTERNAL_MARKET_OBSERVATION: null,
  SCENARIO_ASSUMPTION: "scenario",
  HISTORICAL_OBSERVATION: "historical",
  REALISED_OUTCOME: "realised",
  PRODUCT_RULE: null,
};

export const itemKey = (i: MemoryItem, n: number) => `${i.at ?? "x"}-${i.kind}-${i.report_id ?? i.label}-${n}`;

export const pctPoints = (x: number | null | undefined, digits = 2): string =>
  x == null ? "n/a" : `${x < 0 ? "−" : x > 0 ? "+" : ""}${Math.abs(x * 100).toFixed(digits)}%`;

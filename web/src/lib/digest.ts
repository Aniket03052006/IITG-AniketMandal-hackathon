import type { DrillStep } from "../api/types";

export const SECTION_BLURB: Record<string, string> = {
  NEW_RISKS: "Events that reached the tracking floor in this window.",
  ESCALATIONS: "Severity rose, or coverage describes the event widening or worsening.",
  EXPOSURE_CHANGES: "How much of the book an event reaches changed.",
  STRESS_CHANGES: "The modeled scenario P&L moved: a simulation, not a forecast.",
  EVIDENCE_CHANGES: "Independent corroboration went up or down.",
  CONFLICTS: "Reports now contradict each other on a tracked claim.",
  CONCENTRATION: "Independent events that now share a risk factor and the same holdings.",
  WATCHLISTS: "What happened to the subjects you watch.",
};

/** The drill-down chain from a card to its attribution: each step is a place in the existing Event and Stress pages, never a new page. */
export const DRILL_LABEL: Record<string, string> = {
  EVENT: "Event",
  EVIDENCE: "Evidence",
  SCOPE: "Scope",
  EXPOSURE: "Portfolio exposure",
  PROPAGATION: "Propagation",
  STRESS: "Stress",
  ATTRIBUTION: "Attribution",
};

export function drillTo(step: DrillStep, mode: "REPLAY" | "LIVE", cycle: number | null): string {
  const id = encodeURIComponent(step.signal_id);
  const q = mode === "REPLAY" && cycle != null ? `?cycle=${cycle}` : "";
  switch (step.step) {
    case "EVENT": return `/events/${id}${q}`;
    case "EVIDENCE": return `/events/${id}${q}#evidence`;
    case "SCOPE": return `/events/${id}${q}#intelligence`;
    case "EXPOSURE":
    case "PROPAGATION": return `/events/${id}${q}#stress`;
    case "STRESS": return `/stress?signal=${id}&run=1`;
    default: return `/stress?signal=${id}&run=1`;
  }
}

/** The product story, end to end. Every step is something EventShock derives from the one before it. */
export const STORY: { id: string; label: string; says: string }[] = [
  { id: "information", label: "Information", says: "News and social text from at least two kinds of source, validated and de-duplicated." },
  { id: "understanding", label: "Event understanding", says: "Event type and tone by trained models that can abstain; a transparent severity scorecard." },
  { id: "scope", label: "Scope", says: "Who or what it is about: a company, a sector, a theme, a place, or unresolved (never guessed)." },
  { id: "clustering", label: "Clustering", says: "Reports of one story are one event; every report stays visible." },
  { id: "evidence", label: "Evidence", says: "How well corroborated: independent sources, kept apart from model confidence." },
  { id: "novelty", label: "Novelty and velocity", says: "New, a continuation or an update; how fast it spreads." },
  { id: "conflict", label: "Conflict", says: "Reports that contradict each other on a tracked claim (never from tone)." },
  { id: "lifecycle", label: "Lifecycle", says: "Developing, confirmed, escalating, stabilizing, resolved or stale, by explicit rules." },
  { id: "impact", label: "Impact", says: "Severity 1-10: a triage level, not outcome-calibrated." },
  { id: "materiality", label: "Portfolio materiality", says: "How much of your book it reaches: a lookup, not a score." },
  { id: "propagation", label: "Propagation", says: "How it could reach holdings under stated assumptions: a mapping, not causal inference." },
  { id: "scenario", label: "Scenario", says: "The hypothetical shocks it implies, or SCENARIO UNAVAILABLE." },
  { id: "stress", label: "Stress", says: "The unchanged deterministic engine's result: a simulation, not a forecast." },
  { id: "attribution", label: "Attribution", says: "Why the portfolio moved; adds up to the total." },
  { id: "monitoring", label: "Monitoring", says: "What changed, deterministically in replay and live." },
  { id: "brief", label: "Decision brief", says: "A structured summary of all of the above, with every statement traceable." },
];

import type { EventIntelligence } from "../api/types";

export type Intel = EventIntelligence;

export const SCOPE_TYPE_LABEL: Record<string, string> = {
  COMPANY: "Company",
  INDUSTRY: "Industry",
  SECTOR: "Sector",
  GEOGRAPHY: "Geography",
  MACRO: "Macro",
  MARKET: "Market-wide",
  THEME: "Risk theme",
  UNRESOLVED: "Unresolved",
};

export const SCOPE_TYPE_BLURB: Record<string, string> = {
  COMPANY: "A listed company in the entity master was named.",
  INDUSTRY: "No company named; the text points to one industry.",
  SECTOR: "No company named; the text points to one sector.",
  GEOGRAPHY: "No company or sector named; the text points to a place.",
  MACRO: "A macroeconomic subject: rates, inflation, growth or jobs.",
  MARKET: "The equity market as a whole.",
  THEME: "A risk theme: credit stress, trade and conflict, currencies and commodities.",
  UNRESOLVED: "Nothing defensible could be established. The event is kept, not guessed about.",
};

export const RESOLUTION_LABEL: Record<string, string> = {
  RESOLVED: "Resolved",
  PARTIAL: "Partly resolved",
  AMBIGUOUS: "Ambiguous",
  UNRESOLVED: "Unresolved",
};

export const TIER_LABEL: Record<string, string> = { HIGH: "High", MEDIUM: "Medium", LOW: "Low", NONE: "None" };

export const LIFECYCLE_LABEL: Record<string, string> = {
  DEVELOPING: "Developing",
  CONFIRMED: "Confirmed",
  ESCALATING: "Escalating",
  STABILIZING: "Stabilizing",
  RESOLVED: "Resolved",
  STALE: "Stale",
};

export const LIFECYCLE_BLURB: Record<string, string> = {
  DEVELOPING: "Reported, not yet corroborated by enough independent sources.",
  CONFIRMED: "Independent or authoritative sources carry it, with no open contradiction.",
  ESCALATING: "A report describes it widening or worsening.",
  STABILIZING: "Easing, or no further escalation for the hold period.",
  RESOLVED: "Explicitly resolved, per authoritative or several independent sources.",
  STALE: "No new report for the stale period and no resolution.",
};

export const NOVELTY_LABEL: Record<string, string> = {
  NEW: "New",
  CONTINUATION: "Continuation",
  UPDATE: "Update",
  RECURRING: "Recurring",
  UNKNOWN: "Unknown",
};

export const NOVELTY_BLURB: Record<string, string> = {
  NEW: "Nothing earlier matches this narrative.",
  CONTINUATION: "The same narrative as an earlier event, with nothing new in it.",
  UPDATE: "The same narrative with new numbers or names.",
  RECURRING: "A new occurrence of a narrative that was resolved, went quiet, or is described as another one.",
  UNKNOWN: "Not measurable here; the reason is stated.",
};

export const CONFLICT_LABEL: Record<string, string> = {
  NO_CONFLICT: "No conflict found",
  POSSIBLE_CONFLICT: "Possible conflict",
  CONFLICTED: "Conflicted",
  RESOLVED_CONFLICT: "Conflict resolved",
};

export const STRENGTH_LABEL: Record<string, string> = { STRONG: "Strong", MODERATE: "Moderate", WEAK: "Weak", INSUFFICIENT: "Insufficient" };

export const AVAILABILITY_LABEL: Record<string, string> = {
  AVAILABLE: "Available",
  PARTIAL: "Partial",
  ABSTAINED: "Abstained",
  UNAVAILABLE: "Unavailable",
};

export const factorLabel = (f: string): string =>
  ({ EQUITY: "Equity prices", RATES_BPS: "Interest rates", CREDIT_SPREAD_BPS: "Credit spreads", PD_MULTIPLIER: "Default probability", LGD_ADD: "Loss given default", FX_PCT: "Currencies", COMMODITY_PCT: "Oil price" })[f] ?? f;

export const hoursLabel = (h: number | null | undefined): string =>
  h == null ? "n/a" : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`;

export const when = (iso: string | null | undefined): string =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }) : "n/a";

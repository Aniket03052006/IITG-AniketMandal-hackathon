import type { EventMarketView } from "../api/types";

export const MARKET_LABEL = "EXTERNAL MARKET OBSERVATION";

/** Words for each match status. A status is never shown as a verdict on the event. */
export const MATCH_STATUS: Record<string, { label: string; says: string }> = {
  MATCHED: { label: "Matched", says: "The event reached a market through a curated theme and every gate passed." },
  LOW_CONFIDENCE_MATCH: { label: "Low-confidence match", says: "The theme applies but the text carries only weak evidence of the subject." },
  NO_MATCH: { label: "No match", says: "No relevant external prediction market was identified." },
  INSUFFICIENT_DATA: { label: "Insufficient data", says: "There was not enough resolved information (or provider data) to match honestly." },
};

export const INTERPRETATION: Record<string, string> = {
  MARKET_REPRICED: "Market repriced",
  ALIGNED: "Directionally aligned",
  DIVERGENT: "Divergent",
  LOW_INFORMATION: "Low information",
  NOT_ASSESSED: "Not assessed",
};

/** Signed percentage points, with a true minus sign. */
export const pp = (x: number | null | undefined, digits = 1) => (x == null ? "n/a" : `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x).toFixed(digits)} pp`);

/** The one sentence the card falls back to when there is nothing to show; fixed wording so it can be tested and quoted. */
export function marketFallback(v: EventMarketView): string {
  if (v.availability === "UNAVAILABLE") return "External market data unavailable.";
  if (v.match && v.match.status === "NO_MATCH") return "No relevant external prediction market identified.";
  return v.match?.reason ?? "No relevant external prediction market identified.";
}

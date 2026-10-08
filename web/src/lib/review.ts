import type { ReviewItem, ReviewStatus } from "../api/types";

export const STATUS_TABS: { id: "OPEN" | "REVIEWED" | "DISMISSED" | "ALL"; label: string }[] = [
  { id: "OPEN", label: "Open" },
  { id: "REVIEWED", label: "Reviewed" },
  { id: "DISMISSED", label: "Dismissed" },
  { id: "ALL", label: "All" },
];

export const STATUS_LABEL: Record<ReviewStatus, string> = { OPEN: "Open", REVIEWED: "Reviewed", DISMISSED: "Dismissed" };

/** The tone of a reason chip: what kind of problem it points at. Conflict and a changed event are the ones that most need a person. */
export function reasonTone(code: string): "neg" | "warn" | "demo" {
  return code === "CONFLICTED_CLAIMS" || code === "CHANGED_SINCE_REVIEW" || code === "ESCALATING" ? "neg" : code === "LARGE_STRESS_LOSS" || code === "MATERIAL_TO_BOOK" ? "warn" : "demo";
}

/** One line of what the event is, from fields the queue already carries (no new claim). */
export function factsLine(i: ReviewItem): string {
  const parts: string[] = [];
  parts.push(i.scope_value ? `${i.scope_type.toLowerCase()} · ${i.scope_value}` : i.scope_type.toLowerCase());
  if (i.severity != null) parts.push(`severity ${i.severity}/10`);
  parts.push(`${i.independent_sources} independent ${i.independent_sources === 1 ? "source" : "sources"}`);
  parts.push(`${i.evidence_tier.toLowerCase()} evidence`);
  if (i.materiality && i.materiality !== "NONE") parts.push(`${i.materiality.toLowerCase()} to the book${i.exposure_share != null ? ` (${(i.exposure_share * 100).toFixed(1)}%)` : ""}`);
  return parts.join(" · ");
}

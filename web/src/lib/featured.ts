import type { SignalSummary } from "../api/types";

/**
 * The events the guided demo starts from. They are real replay signals picked for what they teach, never invented or edited:
 *   hero     all-model signal with a clean driver story, a pre-report 8-K, a post-report earnings 8-K and a realised outcome
 *   also     several reports of one story, but a placeholder impact (a weak entity link): shows honest degradation
 * If an id is absent (another data profile), `pickFeatured` falls back to a deterministic rule instead of a broken link.
 */
export const FEATURED = {
  hero: { id: "sig_90ee2542ae", why: "Model-scored, with a filing before the report, one after it, and a realised outcome." },
  also: [{ id: "sig_3c84db95ae", why: "Three outlets reported it, but the impact is a labelled placeholder rule: see how EventShock degrades." }],
} as const;

const LAST_KEY = "eventshock-last-event";

export function rememberEvent(id: string): void {
  try {
    window.sessionStorage.setItem(LAST_KEY, id);
  } catch {
    /* storage blocked: the nav link simply points at the featured event */
  }
}

export function lastEvent(): string | null {
  try {
    return window.sessionStorage.getItem(LAST_KEY);
  } catch {
    return null;
  }
}

const rank = (s: SignalSummary) => [
  s.impact_origin === "MODEL" ? 1 : 0,
  s.entity_id !== "UNKNOWN_ENTITY" ? 1 : 0,
  s.impact_score ?? 0,
  s.source_count,
];

/** The signal the demo opens on: the named hero if present, else the best model-scored, entity-linked, highest-impact classified signal (ties: most recent, then id). */
export function pickFeatured(items: SignalSummary[]): SignalSummary | undefined {
  const named = items.find((s) => s.id === FEATURED.hero.id);
  if (named) return named;
  const pool = items.filter((s) => s.event_status === "CLASSIFIED" && s.impact_score != null);
  return [...pool].sort((a, b) => {
    const ra = rank(a);
    const rb = rank(b);
    for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return rb[i]! - ra[i]!;
    return b.published_at.localeCompare(a.published_at) || a.id.localeCompare(b.id);
  })[0];
}

export function pickAlso(items: SignalSummary[]): SignalSummary[] {
  return FEATURED.also.map((f) => items.find((s) => s.id === f.id)).filter((s): s is SignalSummary => !!s);
}

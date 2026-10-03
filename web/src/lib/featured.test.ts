import { describe, expect, it } from "vitest";
import type { SignalSummary } from "../api/types";
import { FEATURED, pickAlso, pickFeatured } from "./featured";

const sig = (o: Partial<SignalSummary>): SignalSummary =>
  ({ id: "x", event_status: "CLASSIFIED", impact_score: 5, impact_origin: "PLACEHOLDER", entity_id: "E", source_count: 1, published_at: "2026-09-20T00:00:00Z", ...o }) as SignalSummary;

describe("featured event", () => {
  it("opens on the named hero when it exists", () => {
    const items = [sig({ id: "a", impact_score: 9 }), sig({ id: FEATURED.hero.id, impact_score: 7 })];
    expect(pickFeatured(items)?.id).toBe(FEATURED.hero.id);
  });
  it("falls back deterministically: model-scored, entity-linked, highest impact, then latest", () => {
    const items = [
      sig({ id: "placeholder-9", impact_score: 9 }),
      sig({ id: "model-6", impact_score: 6, impact_origin: "MODEL" }),
      sig({ id: "model-7-old", impact_score: 7, impact_origin: "MODEL", published_at: "2026-09-18T00:00:00Z" }),
      sig({ id: "model-7-new", impact_score: 7, impact_origin: "MODEL", published_at: "2026-09-25T00:00:00Z" }),
      sig({ id: "model-8-noentity", impact_score: 8, impact_origin: "MODEL", entity_id: "UNKNOWN_ENTITY" }),
      sig({ id: "nonevent", impact_score: null, event_status: "NO_EVENT" }),
    ];
    expect(pickFeatured(items)?.id).toBe("model-7-new");
    expect(pickFeatured([...items].reverse())?.id).toBe("model-7-new");
  });
  it("returns nothing for an empty feed and ignores absent 'also try' ids", () => {
    expect(pickFeatured([])).toBeUndefined();
    expect(pickAlso([sig({ id: "other" })])).toEqual([]);
  });
});

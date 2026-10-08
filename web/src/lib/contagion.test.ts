import { describe, expect, it } from "vitest";
import type { PropagationGraph } from "../api/types";
import { layoutContagion, wrap } from "./contagion";

export const graph = (over: Record<string, unknown> = {}): PropagationGraph =>
  ({
    signal_id: "s1", version: "propagation-v1", availability: "AVAILABLE", reason: null, portfolio_id: "pf", portfolio_name: "Book", event_category: "GEOPOLITICAL",
    nodes: [
      { id: "event", kind: "EVENT", label: "After Iran Says Strait of Hormuz Is Closed Again, Oil Risk to Economy Rises Once More", detail: null, value: null, share: null },
      { id: "portfolio", kind: "PORTFOLIO", label: "Book", detail: null, value: null, share: 1 },
      { id: "scope:THEME:trade and conflict", kind: "SCOPE", label: "trade and conflict", detail: null, value: null, share: null },
      { id: "scope:GEOGRAPHY:Middle East", kind: "GEOGRAPHY", label: "Middle East", detail: null, value: null, share: 0 },
      { id: "rf:GEOPOLITICAL", kind: "RISK_FACTOR", label: "Geopolitical risk", detail: null, value: null, share: null },
      { id: "rf:OIL_ENERGY", kind: "RISK_FACTOR", label: "Oil and energy prices", detail: null, value: null, share: null },
      { id: "target:ASSET_CLASS:EQUITY", kind: "ASSET_CLASS", label: "Equity positions", detail: null, value: null, share: 0.35 },
      { id: "target:SECTOR:Energy", kind: "SECTOR", label: "Energy", detail: null, value: null, share: 0.09 },
      { id: "target:SECTOR:Consumer", kind: "SECTOR", label: "Consumer", detail: null, value: null, share: 0.36 },
      { id: "target:INDUSTRY:Retail", kind: "INDUSTRY", label: "Retail", detail: null, value: null, share: 0.05 },
      { id: "pos:EQ-NKE", kind: "POSITION", label: "NIKE, Inc. - Common Equity", detail: null, value: null, share: 0.0357 },
      { id: "pos:LN-TGT-19", kind: "POSITION", label: "Target Corporation - Term Loan B", detail: null, value: null, share: 0.0417 },
      { id: "pos:LN-ZZ", kind: "POSITION", label: "Nowhere Corp - Loan", detail: null, value: null, share: 0.01 },
    ],
    edges: [
      { source: "event", target: "scope:THEME:trade and conflict", relationship: "EVIDENCED_BY", rule_id: "r0", basis: "quoted", status: "OBSERVED", weight: null },
      { source: "event", target: "rf:GEOPOLITICAL", relationship: "ABOUT", rule_id: "r1", basis: "text says so", status: "OBSERVED", weight: null },
      { source: "event", target: "rf:OIL_ENERGY", relationship: "ABOUT", rule_id: "r2", basis: "text says oil", status: "OBSERVED", weight: null },
      { source: "rf:GEOPOLITICAL", target: "target:ASSET_CLASS:EQUITY", relationship: "ASSUMED_TRANSMISSION", rule_id: "equities_risk_off", basis: "risk-off", status: "SCENARIO_ASSUMPTION", weight: 1.0 },
      { source: "rf:GEOPOLITICAL", target: "target:SECTOR:Energy", relationship: "ASSUMED_TRANSMISSION", rule_id: "energy_hedge", basis: "energy gains", status: "SCENARIO_ASSUMPTION", weight: -0.5 },
      { source: "rf:OIL_ENERGY", target: "target:SECTOR:Consumer", relationship: "ASSUMED_TRANSMISSION", rule_id: "consumer_cost", basis: "fuel costs", status: "USER_ASSUMPTION", weight: 0.4 },
      { source: "target:SECTOR:Energy", target: "portfolio", relationship: "HELD_BY", rule_id: "h", basis: "held", status: "OBSERVED", weight: null },
      { source: "portfolio", target: "pos:EQ-NKE", relationship: "HELD_BY", rule_id: "h", basis: "held", status: "OBSERVED", weight: null },
    ],
    active_factors: [], reached: [
      { asset_id: "EQ-NKE", name: "NIKE, Inc. - Common Equity", entity_id: "E", asset_type: "EQUITY", sector: "Consumer", industry: null, geography: "US", market_value: 3, share: 0.0357, basis: "EVIDENCED_SCOPE", routes: [] },
      { asset_id: "LN-TGT-19", name: "Target Corporation - Term Loan B", entity_id: "E", asset_type: "LOAN", sector: "Consumer", industry: "Retail", geography: "US", market_value: 4, share: 0.0417, basis: "ASSUMPTION_ONLY", routes: [] },
      { asset_id: "LN-ZZ", name: "Nowhere Corp - Loan", entity_id: "E", asset_type: "LOAN", sector: "Utilities", industry: null, geography: "US", market_value: 1, share: 0.01, basis: "ASSUMPTION_ONLY", routes: [] },
    ],
    reached_value: 8, reached_share: 0.09, direct_share: 0, indirect_share: 0.09, evidenced_share: 0.04, assumed_share: 0.05, mapping_basis: "EVIDENCED_SCOPE", not_reached: [], labels: [], limitations: [],
    ...over,
  }) as unknown as PropagationGraph;

describe("wrap", () => {
  it("wraps at word boundaries and ends an overflowing text with an ellipsis", () => {
    expect(wrap("Equity positions", 27, 2)).toEqual(["Equity positions"]);
    expect(wrap("After Iran Says Strait of Hormuz Is Closed Again", 30, 2)).toEqual(["After Iran Says Strait of", "Hormuz Is Closed Again"]); // "…Strait of Hormuz" is 32 characters, over the limit of 30
    const w = wrap("one two three four five six seven eight nine ten", 10, 2);
    expect(w).toHaveLength(2);
    expect(w[1]!.endsWith("…")).toBe(true);
    expect(wrap("Supercalifragilisticexpialidocious", 10, 1)[0]!.length).toBeLessThanOrEqual(10);
    expect(wrap("   ", 10, 2)).toEqual([""]);
  });
});

describe("layoutContagion", () => {
  it("puts the event, risk factors, landing places and holdings in four columns, left to right", () => {
    const l = layoutContagion(graph())!;
    const col = (kind: string) => l.nodes.filter((n) => n.kind === kind);
    expect(col("event")).toHaveLength(1);
    expect(col("factor").map((n) => n.full)).toEqual(["Geopolitical risk", "Oil and energy prices"]);
    expect(col("target").map((n) => n.full)).toEqual(["Consumer", "Equity positions", "Energy", "Retail"]); // largest share of the book first
    expect(col("holding")).toHaveLength(3);
    const xs = ["event", "factor", "target", "holding"].map((k) => col(k)[0]!.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(l.columns.map((c) => c.title)).toEqual(["Event", "Risk factors", "Where it lands", "Largest holdings reached"]);
    expect(l.nodes.every((n) => n.x >= 0 && n.x + n.w <= l.width && n.y >= 0 && n.y + n.h <= l.height)).toBe(true);
  });

  it("wraps every label to the width of its box", () => {
    const l = layoutContagion(graph())!;
    expect(l.nodes.every((n) => n.lines.every((line) => line.length <= 23) && n.subLines.every((line) => line.length <= 26))).toBe(true);
    expect(l.nodes.every((n) => n.h === 18 + 14 * (n.lines.length + n.subLines.length))).toBe(true); // the box is exactly as tall as its text
  });

  it("does not overlap boxes within a column", () => {
    const l = layoutContagion(graph())!;
    for (const k of ["event", "factor", "target", "holding"]) {
      const c = l.nodes.filter((n) => n.kind === k).sort((a, b) => a.y - b.y);
      for (let i = 1; i < c.length; i++) expect(c[i]!.y).toBeGreaterThanOrEqual(c[i - 1]!.y + c[i - 1]!.h);
    }
  });

  it("keeps each graph edge between adjacent columns with its status and the sign of its weight, and drops the ones that are not part of the picture", () => {
    const l = layoutContagion(graph())!;
    const e = (s: string, t: string) => l.edges.find((x) => x.source === s && x.target === t)!;
    expect(e("event", "rf:GEOPOLITICAL")).toMatchObject({ status: "OBSERVED", tone: "neutral", origin: "graph" });
    expect(e("rf:GEOPOLITICAL", "target:ASSET_CLASS:EQUITY")).toMatchObject({ status: "SCENARIO_ASSUMPTION", tone: "hurts", weight: 1 });
    expect(e("rf:GEOPOLITICAL", "target:SECTOR:Energy")).toMatchObject({ tone: "benefits", weight: -0.5 });
    expect(e("rf:OIL_ENERGY", "target:SECTOR:Consumer")).toMatchObject({ status: "USER_ASSUMPTION", tone: "hurts" });
    // subject nodes and the book's HELD_BY edges are not drawn; every drawn edge points left to right
    expect(l.edges.some((x) => x.source.startsWith("scope:") || x.target.startsWith("scope:") || x.target === "portfolio" || x.source === "portfolio")).toBe(false);
    const at = new Map(l.nodes.map((n) => [n.id, n]));
    expect(l.edges.every((x) => at.get(x.source)!.x < at.get(x.target)!.x)).toBe(true);
  });

  it("connects a holding to the sector, industry and asset class it is in, as observed facts, and to nothing it is not in", () => {
    const l = layoutContagion(graph())!;
    const into = (id: string) => l.edges.filter((x) => x.target === id).map((x) => x.source).sort();
    expect(into("pos:EQ-NKE")).toEqual(["target:ASSET_CLASS:EQUITY", "target:SECTOR:Consumer"]);
    expect(into("pos:LN-TGT-19")).toEqual(["target:INDUSTRY:Retail", "target:SECTOR:Consumer"]);
    expect(into("pos:LN-ZZ")).toEqual([]); // Utilities is not a landing place here
    expect(l.edges.filter((x) => x.origin === "held").every((x) => x.status === "OBSERVED" && x.rule === "held_in")).toBe(true);
  });

  it("shows the largest holdings and says how many were reached", () => {
    const l = layoutContagion(graph(), 2)!;
    expect(l.nodes.filter((n) => n.kind === "holding")).toHaveLength(2);
    expect(l.holdingsShown).toBe(2);
    expect(l.holdingsReached).toBe(3);
  });

  it("states the subjects the event is about in the event box", () => {
    const l = layoutContagion(graph())!;
    const event = l.nodes.find((n) => n.kind === "event")!;
    expect(event.sub).toBe("About: trade and conflict · Middle East");
    expect(event.subLines.join(" ")).toBe(event.sub); // wrapped to the box, nothing lost
    expect(event.subLines.every((line) => line.length <= 26)).toBe(true);
  });

  it("draws nothing when the graph abstained or has no risk factor or landing place", () => {
    expect(layoutContagion(graph({ availability: "ABSTAINED" }))).toBeNull();
    expect(layoutContagion(graph({ nodes: graph().nodes.filter((n) => n.kind !== "RISK_FACTOR") }))).toBeNull();
    expect(layoutContagion(graph({ nodes: graph().nodes.filter((n) => !["SECTOR", "ASSET_CLASS", "INDUSTRY"].includes(n.kind)) }))).toBeNull();
  });

  it("is deterministic: the same graph gives the same picture", () => {
    expect(JSON.stringify(layoutContagion(graph()))).toBe(JSON.stringify(layoutContagion(graph())));
  });
});

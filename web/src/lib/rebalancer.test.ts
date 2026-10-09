import { describe, expect, it } from "vitest";
import type { IndexConstituent } from "../api/types";
import { decisions } from "../components/rebalancer/rebalancer.fixtures";
import { ageText, areaPath, CONSTRAINT_LABEL, isRiskRule, nearestIndex, orderSeries, pp, previewApproval, spreadLabels, stackLayers, tradeText, tradesOf, turnoverBetween } from "./rebalancer";

const con = (ticker: string, sector: string): IndexConstituent => ({ ticker, name: `${ticker} Corp`, sector, benchmark_weight: 0.25, lower: 0.1, upper: 0.4 });
const cons = [con("MSFT", "Technology"), con("JPM", "Financials"), con("AAPL", "Technology"), con("XOM", "Energy")];
const tickers = ["MSFT", "JPM", "AAPL", "XOM"];

describe("orderSeries", () => {
  it("keeps a sector's stocks together, in the sector order, then by ticker", () => {
    const s = orderSeries(cons, tickers);
    expect(s.map((x) => x.ticker)).toEqual(["AAPL", "MSFT", "JPM", "XOM"]);
    expect(s.map((x) => x.index)).toEqual([2, 0, 1, 3]);
  });
  it("lightens the hue step by step inside a sector but never to nothing", () => {
    const [a, m] = orderSeries(cons, tickers);
    expect(a!.fill).toContain("100%");
    expect(m!.fill).toMatch(/62%/);
    expect(a!.stroke).toBe("var(--color-sector-technology)");
  });
  it("uses only token references (no colour literal)", () => {
    for (const s of orderSeries(cons, tickers)) expect(s.fill + s.stroke).not.toMatch(/#|rgb|oklch\(|hsl/);
  });
  it("gives an unknown sector the neutral muted token instead of failing", () => {
    expect(orderSeries([con("ZZZ", "Space")], ["ZZZ"])[0]!.stroke).toBe("var(--color-muted)");
  });
  it("ignores a constituent with no column in the timeline", () => {
    expect(orderSeries(cons, ["AAPL"]).map((s) => s.ticker)).toEqual(["AAPL"]);
  });
});

describe("stackLayers", () => {
  const weights = [[0.25, 0.25, 0.25, 0.25], [0.3, 0.2, 0.3, 0.2]];
  it("stacks to the column total and the last band tops out at 1", () => {
    const layers = stackLayers(weights, orderSeries(cons, tickers));
    expect(layers[layers.length - 1]!.top).toEqual([1, 1].map((v) => expect.closeTo(v, 12)));
    expect(layers[0]!.bottom).toEqual([0, 0]);
    expect(layers[1]!.bottom).toEqual(layers[0]!.top);
  });
  it("band thickness equals the stock's weight", () => {
    const layers = stackLayers(weights, orderSeries(cons, tickers));
    const aapl = layers[0]!;
    expect(aapl.top[1]! - aapl.bottom[1]!).toBeCloseTo(0.3, 12);
  });
});

describe("spreadLabels", () => {
  it("separates overlapping labels by the gap and keeps their order", () => {
    const out = spreadLabels([10, 11, 12, 100], 12, 0, 200);
    expect(out[1]! - out[0]!).toBeGreaterThanOrEqual(12);
    expect(out[2]! - out[1]!).toBeGreaterThanOrEqual(12);
    expect(out[3]).toBe(100);
  });
  it("stays inside the range even when pushed past the bottom", () => {
    const out = spreadLabels([190, 195, 199, 200], 12, 0, 200);
    expect(Math.max(...out)).toBeLessThanOrEqual(200);
    expect(Math.min(...out)).toBeGreaterThanOrEqual(0);
    const sorted = [...out].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++) expect(sorted[i]! - sorted[i - 1]!).toBeGreaterThanOrEqual(12 - 1e-9);
  });
  it("returns positions in the input order", () => {
    const out = spreadLabels([50, 10], 12, 0, 100);
    expect(out[0]).toBe(50);
    expect(out[1]).toBe(10);
  });
});

describe("paths", () => {
  it("closes the area between two polylines", () => {
    const d = areaPath([0, 10], [1, 1], [0, 0], (v) => 100 - v * 100);
    expect(d.startsWith("M0.0 0.0")).toBe(true);
    expect(d.endsWith("Z")).toBe(true);
  });
});

describe("formatting and trades", () => {
  it("prints signed percentage points and never '+0.00' or '-0.00'", () => {
    expect(pp(0.0125)).toBe("+1.25 pp");
    expect(pp(-0.0125)).toBe("-1.25 pp");
    expect(pp(0)).toBe("0.00 pp");
    expect(pp(-0.0000001)).toBe("0.00 pp");
  });
  it("lists trades largest first and drops rounding noise", () => {
    const t = tradesOf([{ ticker: "A", change: 0.001 }, { ticker: "B", change: -0.004 }, { ticker: "C", change: 1e-9 }]);
    expect(t.map((x) => `${x.side} ${x.ticker}`)).toEqual(["SELL B", "BUY A"]);
  });
  it("maps a pointer to the nearest cycle and clamps outside the plot", () => {
    const xs = [0, 10, 20, 30];
    expect(nearestIndex(14, 0, 30, xs)).toBe(1);
    expect(nearestIndex(-50, 0, 30, xs)).toBe(0);
    expect(nearestIndex(500, 0, 30, xs)).toBe(3);
  });
});

describe("tradeText and ageText", () => {
  it("says the side in words, never only with a sign or a colour", () => {
    expect(tradeText({ side: "BUY", trade: 0.03 })).toBe("Buy 3.00 pp");
    expect(tradeText({ side: "SELL", trade: -0.0125 })).toBe("Sell 1.25 pp");
    expect(tradeText({ side: "HOLD", trade: 0 })).toBe("No trade");
  });
  it("writes an age a person can read", () => {
    expect(ageText(null)).toBe("none");
    expect(ageText(0.3)).toBe("under an hour");
    expect(ageText(14.4)).toBe("14 h");
    expect(ageText(72)).toBe("3.0 days");
  });
});

describe("constraint vocabulary", () => {
  it("names every rule and separates a risk rule from the pacing of the trade", () => {
    expect(Object.keys(CONSTRAINT_LABEL)).toHaveLength(7);
    expect(isRiskRule("SECTOR_CAP")).toBe(true);
    expect(isRiskRule("TURNOVER_CAP")).toBe(false);
    expect(isRiskRule("MIN_TRADE")).toBe(false);
  });
});

describe("previewApproval", () => {
  const p = decisions();
  const t = p.tickers;
  const sum = (w: number[]) => w.reduce((a, b) => a + b, 0);
  it("approving everything is the proposal exactly", () => {
    const r = previewApproval(p.decisions, t, null);
    expect(r.weights).toEqual(t.map((x) => p.decisions.find((d) => d.ticker === x)!.after));
    expect(r.problem).toBeNull();
    expect(r.rejected).toEqual([]);
  });
  it("a partial approval keeps the index fully invested and each weight between its old and new value", () => {
    const r = previewApproval(p.decisions, t, new Set(["NVDA", "JPM"]));
    expect(r.problem).toBeNull();
    expect(sum(r.weights)).toBeCloseTo(1, 12);
    expect(r.rejected).toEqual(["AAPL"]);
    t.forEach((x, i) => {
      const d = p.decisions.find((y) => y.ticker === x)!;
      expect(r.weights[i]!).toBeGreaterThanOrEqual(Math.min(d.before, d.after) - 1e-12);
      expect(r.weights[i]!).toBeLessThanOrEqual(Math.max(d.before, d.after) + 1e-12);
    });
  });
  it("scales the larger side down so what is bought equals what is sold", () => {
    const r = previewApproval(p.decisions, t, new Set(["NVDA", "AAPL"]));   // buy 3.00 pp, sell 1.00 pp
    const nv = r.weights[t.indexOf("NVDA")]! - 0.28;
    expect(nv).toBeCloseTo(0.01, 12);
    expect(sum(r.weights)).toBeCloseTo(1, 12);
  });
  it("refuses a selection with only buys or only sells, and falls back to the old weights", () => {
    const r = previewApproval(p.decisions, t, new Set(["NVDA"]));
    expect(r.problem).toMatch(/paid for by a sell/);
    expect(r.weights).toEqual(t.map((x) => p.decisions.find((d) => d.ticker === x)!.before));
    expect(previewApproval(p.decisions, t, new Set()).problem).toBeNull();   // accepting nothing is allowed: nothing is bought and nothing is sold
  });
  it("measures turnover as one-way", () => {
    expect(turnoverBetween([0.5, 0.5], [0.6, 0.4])).toBeCloseTo(0.1);
  });
});

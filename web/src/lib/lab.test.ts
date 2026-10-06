import { describe, expect, it } from "vitest";
import { blankRow, displayUnit, fmt, fromValue, toRequest, toValue, type Draft } from "./lab";

describe("lab units", () => {
  it("reads what a person types in the unit shown: percent for fractions, bp, multipliers", () => {
    expect(toValue("-10", "fraction")).toBeCloseTo(-0.1);
    expect(toValue("−5.5", "fraction")).toBeCloseTo(-0.055);          // a typographic minus is accepted
    expect(toValue("75", "bp")).toBe(75);
    expect(toValue("2", "multiplier")).toBe(2);
    for (const bad of ["", " ", "-", "abc", "1e999", "NaN"]) expect(toValue(bad, "bp")).toBeNull();
  });
  it("round-trips and formats with an explicit sign", () => {
    expect(fromValue(-0.1, "fraction")).toBe("-10");
    expect(fromValue(75, "bp")).toBe("75");
    expect(fmt(-0.1, "fraction")).toBe("−10.0%");
    expect(fmt(0.05, "fraction")).toBe("+5.0%");
    expect(fmt(100, "bp")).toBe("+100 bp");
    expect(fmt(2, "multiplier")).toBe("×2.00");
    expect(displayUnit("fraction")).toBe("%");
  });
});

describe("toRequest", () => {
  const kinds = [{ kind: "EQUITY_MARKET", label: "", unit: "fraction", min: -0.8, max: 0.5, needs_target: null, reaches: "" }, { kind: "RATES", label: "", unit: "bp", min: -500, max: 500, needs_target: null, reaches: "" }] as never;
  const draft = (rows: Draft["rows"], type: Draft["type"] = "CUSTOM"): Draft => ({ id: "d", type, name: " Mine ", rows, exposurePriors: true, signalId: "sig_1" });
  it("converts typed sizes to engine units and leaves out rows with no number, saying how many", () => {
    const { body, skipped } = toRequest(draft([{ ...blankRow("EQUITY_MARKET"), value: "-10" }, { ...blankRow("RATES"), value: "75", target: " " }, { ...blankRow("RATES"), value: "" }]), kinds, () => "fraction");
    expect(skipped).toBe(1);
    expect(body.assumptions).toEqual([{ kind: "EQUITY_MARKET", value: -0.1, target: null, rationale: "" }, { kind: "RATES", value: 75, target: null, rationale: "" }]);
    expect(body).toMatchObject({ scenario_type: "CUSTOM", name: "Mine", exposure_priors: true });
  });
  it("sends no assumptions for a BASE or ASSESSED scenario, whatever the rows hold", () => {
    expect(toRequest(draft([{ ...blankRow(), value: "-5" }], "BASE"), kinds, () => "fraction").body.assumptions).toEqual([]);
    expect(toRequest(draft([], "ASSESSED"), kinds, () => "fraction").body).toMatchObject({ scenario_type: "ASSESSED", signal_id: "sig_1", assumptions: [] });
  });
  it("uses the risk factor's own unit for a risk-factor row", () => {
    const { body } = toRequest(draft([{ ...blankRow("RISK_FACTOR"), target: "RATES", value: "50" }]), kinds, (t) => (t === "RATES" ? "bp" : "fraction"));
    expect(body.assumptions?.[0]).toMatchObject({ kind: "RISK_FACTOR", value: 50, target: "RATES" });
  });
});

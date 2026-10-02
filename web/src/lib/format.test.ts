import { ago, money, moneyFull, pct, shockValue, signed } from "./format";

describe("money", () => {
  it("compacts by magnitude", () => {
    expect(money(558_798_258)).toBe("$558.8M");
    expect(money(12_400)).toBe("$12.4K");
    expect(money(950)).toBe("$950");
    expect(money(2_500_000_000)).toBe("$2.50B");
  });
  it("uses a true minus sign and optional plus", () => {
    expect(money(-10_173_459)).toBe("−$10.2M");
    expect(money(4_000, { signed: true })).toBe("+$4.0K");
  });
  it("prints full values with separators", () => {
    expect(moneyFull(-1234567.4)).toBe("−$1,234,567");
  });
});

describe("pct / signed", () => {
  it("formats percentages", () => {
    expect(pct(-0.018205, 2, true)).toBe("−1.82%");
    expect(pct(0.5, 0)).toBe("50%");
    expect(pct(0.03, 1, true)).toBe("+3.0%");
  });
  it("signs numbers", () => {
    expect(signed(-0.72)).toBe("−0.72");
    expect(signed(0.14)).toBe("+0.14");
    expect(signed(0)).toBe("0.00");
  });
});

describe("shockValue", () => {
  it.each([
    ["EQUITY", -0.1, "−10.0%"],
    ["RATES_BPS", 100, "+100 bp"],
    ["CREDIT_SPREAD_BPS", -20, "−20 bp"],
    ["PD_MULTIPLIER", 2.29, "2.29×"],
    ["LGD_ADD", 0.129, "+12.9 pp"],
  ])("%s", (factor, v, out) => expect(shockValue(factor, v)).toBe(out));
});

describe("ago (relative to the replay clock)", () => {
  const asOf = "2026-10-01T12:00:00Z";
  it.each([
    ["2026-10-01T11:58:00Z", "2m ago"],
    ["2026-10-01T08:30:00Z", "3.5h ago"],
    ["2026-10-01T06:00:00Z", "6h ago"],
    ["2026-09-28T12:00:00Z", "3d ago"],
    ["2026-10-01T12:00:00Z", "now"],
  ])("%s", (iso, out) => expect(ago(iso, asOf)).toBe(out));
  it("never goes negative for future timestamps", () => {
    expect(ago("2026-10-02T00:00:00Z", asOf)).toBe("now");
  });
});

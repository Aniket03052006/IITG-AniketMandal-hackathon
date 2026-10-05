import { describe, expect, it } from "vitest";
import { emptyForm, emptyRow, fromInput, hasContent, num, toInput } from "./portfolioForm";

describe("portfolio form", () => {
  it("reads numbers the way people type them", () => {
    expect(num("1,250.5")).toBe(1250.5);
    expect(num(" 20 ")).toBe(20);
    expect(num("")).toBeNull();
    expect(num("abc")).toBeNull();
  });

  it("builds a weight-mode payload and drops the quantity fields", () => {
    const f = emptyForm();
    f.rows = [
      { ...emptyRow(), ticker: "AAPL", weight: "60", quantity: "9", price: "9" },
      { ...emptyRow(), ticker: "cash", weight: "40", currency: "usd" },
    ];
    const p = toInput(f);
    expect(p.mode).toBe("WEIGHT");
    expect(p.holdings[0]).toMatchObject({ ticker: "AAPL", weight_pct: 60, quantity: null, price: null });
    expect(p.holdings[1]).toMatchObject({ ticker: "cash", weight_pct: 40, currency: "USD" });
  });

  it("builds a quantity-mode payload with no weights or total", () => {
    const f = emptyForm();
    f.mode = "QUANTITY";
    f.totalValue = "500000";
    f.rows = [{ ...emptyRow(), ticker: "AAPL", quantity: "100", price: "190", weight: "5", cost: "150" }];
    const p = toInput(f);
    expect(p.total_value).toBeNull();
    expect(p.holdings[0]).toMatchObject({ weight_pct: null, quantity: 100, price: 190, cost_basis: 150 });
  });

  it("skips untouched rows and round-trips a stored portfolio", () => {
    const f = emptyForm();
    f.rows = [{ ...emptyRow(), ticker: "JPM", weight: "100", beta: "1.1", sector: "Financials" }, emptyRow()];
    const p = toInput(f);
    expect(p.holdings).toHaveLength(1);
    const back = fromInput(p);
    expect(back.rows[0]).toMatchObject({ ticker: "JPM", weight: "100", beta: "1.1", sector: "Financials" });
    expect(hasContent(back)).toBe(true);
    expect(hasContent(emptyForm())).toBe(false);
  });
});

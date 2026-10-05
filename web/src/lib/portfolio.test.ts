import { afterEach, describe, expect, it } from "vitest";
import { currencySymbol, getActivePortfolio, parsePortfolioId, pfParam, resetActivePortfolioForTests, resolveActivePortfolio, setActivePortfolio } from "./portfolio";

afterEach(() => {
  window.localStorage.clear();
  resetActivePortfolioForTests();
});

describe("active portfolio (optional; null = the synthetic default)", () => {
  it("accepts only saved-portfolio ids", () => {
    expect(parsePortfolioId("pf_abc123def4")).toBe("pf_abc123def4");
    for (const bad of ["default", "", null, undefined, "../x", "pf_", "PF_ABC123"]) expect(parsePortfolioId(bad as string | null)).toBeNull();
  });

  it("lets the URL beat storage, and ?portfolio=default force the default", () => {
    expect(resolveActivePortfolio("", "pf_stored0001")).toBe("pf_stored0001");
    expect(resolveActivePortfolio("?portfolio=pf_fromurl001", "pf_stored0001")).toBe("pf_fromurl001");
    expect(resolveActivePortfolio("?portfolio=default", "pf_stored0001")).toBeNull();
    expect(resolveActivePortfolio("", null)).toBeNull();
  });

  it("chooses, persists and goes back to the default", () => {
    expect(getActivePortfolio()).toBeNull();
    setActivePortfolio("pf_mine000001");
    expect(getActivePortfolio()).toBe("pf_mine000001");
    expect(window.localStorage.getItem("eventshock-portfolio")).toBe("pf_mine000001");
    setActivePortfolio(null);
    expect(getActivePortfolio()).toBeNull();
    expect(window.localStorage.getItem("eventshock-portfolio")).toBeNull();
  });

  it("works with blocked storage", () => {
    const orig = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("blocked");
    };
    try {
      setActivePortfolio("pf_mine000001");
      expect(getActivePortfolio()).toBe("pf_mine000001");
    } finally {
      Storage.prototype.setItem = orig;
    }
  });

  it("adds nothing to a default request", () => {
    expect(pfParam(null)).toBe("");
    expect(pfParam("pf_mine000001")).toBe("portfolio_id=pf_mine000001");
    expect(currencySymbol("INR")).toBe("₹");
    expect(currencySymbol("CHF")).toBe("CHF ");
    expect(currencySymbol(undefined)).toBe("$");
  });
});

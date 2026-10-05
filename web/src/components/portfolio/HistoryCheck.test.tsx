import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ScenarioHistoryCheck } from "../../api/types";
import { HistoryCheckView } from "./HistoryCheck";

const check: ScenarioHistoryCheck = {
  scenario_id: "scn_macro_rates_shock", severity_scale: 1, first_session: "2014-01-02", last_session: "2026-10-01",
  checks: [
    { factor: "EQUITY", scope: "MARKET", value: -0.06, unit: "fraction", checkable: true, basis: "the S&P 500", horizons: [], reading: "A −6.0% move in the S&P 500, historically over 1 session: about 1 window in 9,000." },
    { factor: "RATES_BPS", scope: "MARKET", value: 100, unit: "bp", checkable: true, basis: "the 10-year Treasury yield (bp)", horizons: [], reading: "A +100 bp move in the 10-year Treasury yield (bp), historically over 21 sessions: larger than any on record (worst +93 bp)." },
    { factor: "PD_MULTIPLIER", scope: "MARKET", value: 1.2, unit: "x", checkable: false, basis: "no default history is held", horizons: [], reading: "Not checkable against history: no default history is held. The magnitude is an unvalidated assumption." },
  ],
  caveats: ["A percentile is a historical frequency of a move at least this large over the stated horizon, not a probability that the scenario occurs."],
};

describe("HistoryCheckView", () => {
  it("shows each shock as applied with its place in history, and says when history cannot speak to it", () => {
    render(<HistoryCheckView check={check} />);
    const t = screen.getByRole("table", { name: /each scenario shock against history/i });
    expect(within(t).getByText(/about 1 window in 9,000/)).toBeInTheDocument();
    expect(within(t).getByText(/larger than any on record/)).toBeInTheDocument();
    expect(within(t).getByText("+100 bp")).toBeInTheDocument();
    expect(within(t).getByText("−6.0%")).toBeInTheDocument();
    expect(within(t).getByText(/Not checkable against history/)).toBeInTheDocument();
    expect(within(t).getByText(/unvalidated assumption/)).toBeInTheDocument();
  });

  it("keeps the caveat that a percentile is not a probability, and the span of history used", () => {
    render(<HistoryCheckView check={check} />);
    expect(screen.getByText(/not a probability that the scenario occurs/)).toBeInTheDocument();
    expect(screen.getByText(/2014-01-02 to 2026-10-01/)).toBeInTheDocument();
  });
});

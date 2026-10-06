import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LabOptions, ReverseStressResult } from "../../api/types";
import { ReverseResultView, ReverseStress } from "./ReverseStress";

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const rev = (over: Partial<ReverseStressResult> = {}): ReverseStressResult =>
  ({
    version: "lab-v1", reverse_id: "rev_abc", status: "ACHIEVABLE", portfolio_id: "default", portfolio_name: "Book", target_pct: -5, achieved_pct: -5.0025, difference_pp: -0.0025, achieved_pnl: -65000, baseline_value: 1300000,
    required_shocks: [
      { axis: "EQUITY_MARKET", label: "Equity market", kind: "EQUITY_MARKET", target: null, value: -0.0542, unit: "fraction", bound: 0.4, share_of_bound: 0.135, label_kind: "SCENARIO ASSUMPTION" },
      { axis: "RATES", label: "Interest rates", kind: "RATES", target: null, value: 40.6, unit: "bp", bound: 300, share_of_bound: 0.135, label_kind: "SCENARIO ASSUMPTION" },
    ],
    dominant_drivers: ["Market-wide shocks", "equity price shock"], affected_holdings: ["JPMorgan Chase", "Microsoft"], affected_sectors: ["Financials", "Technology"], affected_risk_factors: ["Equity market level", "Interest rates"],
    binding_bounds: [], bounds: [{ axis: "EQUITY_MARKET", label: "Equity market", unit: "fraction", bound: 0.4, direction: "ADVERSE_DOWN", efficiency: -33.2, used: true, note: null }, { axis: "CREDIT_SPREAD", label: "Credit spreads", unit: "bp", bound: 400, direction: "ADVERSE_UP", efficiency: 0, used: false, note: "reaches nothing, or only gains, in its adverse direction: not used" }],
    assumptions: ["Every shock found is a SCENARIO ASSUMPTION."], search_method: "BOUNDED_GRID_MINIMAX", search_config: { objective: "reach the target with the smallest largest share of any bound", tolerance_pp: 0.02 }, evaluations: 75, scenario: null,
    open_in_lab: { scenario_type: "CUSTOM", name: "Reverse stress -5%", assumptions: [], signal_id: null, portfolio_id: null, exposure_priors: false, force: false } as never, exposure_priors: [],
    label: "SCENARIO ASSUMPTION", note: "A hypothetical stress analysis: the shocks above are what it would take, under these bounds, to lose this much. It is not a prediction of future losses.", labels: [], limitations: ["The basket is configured judgement."], ...over,
  }) as ReverseStressResult;

describe("ReverseResultView", () => {
  it("shows target, achieved, status, the required shocks as assumptions, the dominant driver and the note", () => {
    wrap(<ReverseResultView r={rev()} />);
    expect(screen.getByText("−5.0%")).toBeInTheDocument();
    expect(screen.getByText("−5.00%")).toBeInTheDocument();
    expect(screen.getAllByText("Achievable").length).toBeGreaterThan(0);
    const list = screen.getByRole("list", { name: "Required shocks" });
    expect(within(list).getByText("−5.4%")).toBeInTheDocument();
    expect(within(list).getByText("+41 bp")).toBeInTheDocument();
    expect(within(list).getAllByText("SCENARIO ASSUMPTION")).toHaveLength(2);
    expect(screen.getByText("Market-wide shocks")).toBeInTheDocument();
    expect(screen.getByText(/not a prediction of future losses/i)).toBeInTheDocument();
  });

  it("says when the target is out of reach, which axes are at their limit, and how far short it fell", () => {
    wrap(<ReverseResultView r={rev({ status: "NOT_ACHIEVABLE", target_pct: -60, achieved_pct: -36.9, difference_pp: 23.1, binding_bounds: ["EQUITY_MARKET", "RATES"] })} />);
    expect(screen.getAllByText("Not achievable within the bounds").length).toBeGreaterThan(0);
    expect(screen.getByText("The configured bounds cannot reach this loss.")).toBeInTheDocument();
    expect(screen.getByText(/EQUITY_MARKET, RATES at their limit/)).toBeInTheDocument();
    expect(screen.getByText("Shocks at the limit")).toBeInTheDocument();
    expect(screen.getByText(/short of it/)).toBeInTheDocument();
  });

  it("explains a book the basket cannot reach", () => {
    wrap(<ReverseResultView r={rev({ status: "NO_EXPOSURE", achieved_pct: null, difference_pp: null, required_shocks: [], dominant_drivers: [] })} />);
    expect(screen.getByText("No shock in the basket reaches this portfolio.")).toBeInTheDocument();
  });

  it("lists the bounds and how it searched on demand and forks the combination into the lab", async () => {
    const onFork = vi.fn();
    wrap(<ReverseResultView r={rev()} onFork={onFork} />);
    await userEvent.click(screen.getByText("Bounds and how it searched"));
    const t = screen.getByRole("table", { name: /configured bounds/i });
    expect(within(t).getByText(/reaches nothing, or only gains/)).toBeInTheDocument();
    expect(screen.getByText(/75 engine evaluations/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open in the lab" }));
    expect(onFork).toHaveBeenCalledWith(expect.objectContaining({ scenario_type: "CUSTOM", name: "Reverse stress -5%" }));
  });
});

const options = { reverse: { presets_pct: [-2, -5, -10], min_target_pct: -95, tolerance_pp: 0.02, method: "BOUNDED_GRID_MINIMAX", axes: [] } } as unknown as LabOptions;

describe("ReverseStress", () => {
  function stub() {
    const calls: { url: string; body?: { target_pct: number; exposure_priors: boolean } }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ url, body });
      const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/lab/options")) return json(options);
      if (url === "/api/reverse-stress") return json(rev({ target_pct: body.target_pct }));
      return json({ detail: "nope" }, 404);
    }));
    return calls;
  }

  it("runs a preset in one click", async () => {
    const calls = stub();
    wrap(<ReverseStress />);
    await userEvent.click(await screen.findByRole("button", { name: "−5%" }));
    await screen.findByLabelText("Reverse stress result");
    expect(calls.find((c) => c.url === "/api/reverse-stress")?.body).toEqual({ target_pct: -5, exposure_priors: false, portfolio_id: null });
  });

  it("validates a custom loss before sending it", async () => {
    const calls = stub();
    wrap(<ReverseStress />);
    const input = await screen.findByLabelText("Custom target loss in percent");
    const go = screen.getByRole("button", { name: "Find the shocks" });
    expect(go).toBeDisabled();
    await userEvent.type(input, "5");
    expect(screen.getByText(/Enter a loss between -95% and 0%/)).toBeInTheDocument();
    expect(go).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, "-7.5");
    expect(go).toBeEnabled();
    await userEvent.click(screen.getByLabelText(/estimate oil exposure/i));
    await userEvent.click(go);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/reverse-stress")).toBe(true));
    expect(calls.find((c) => c.url === "/api/reverse-stress")?.body).toMatchObject({ target_pct: -7.5, exposure_priors: true });
  });
});

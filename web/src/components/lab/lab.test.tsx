import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LabComparison, LabOptions, LabResult } from "../../api/types";
import { CompareView } from "./CompareView";
import { LabResultView } from "./LabResultView";
import { ScenarioLab } from "./ScenarioLab";

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const options: LabOptions = {
  version: "lab-v1", portfolio_id: "default", base_currency: "USD", label: "SCENARIO ASSUMPTION", max_assumptions: 12, max_compared: 3, held_currencies: [], oil_priors: [],
  kinds: [
    { kind: "EQUITY_MARKET", label: "Equity market", unit: "fraction", min: -0.8, max: 0.5, needs_target: null, reaches: "every equity at its beta" },
    { kind: "RATES", label: "Interest rates (parallel)", unit: "bp", min: -500, max: 500, needs_target: null, reaches: "bonds" },
    { kind: "COMMODITY", label: "Oil price", unit: "fraction", min: -0.9, max: 1, needs_target: null, reaches: "positions with an oil elasticity" },
    { kind: "FX", label: "Currency", unit: "fraction", min: -0.6, max: 0.6, needs_target: "a currency code", reaches: "positions held in that currency" },
    { kind: "SECTOR", label: "Sector equities", unit: "fraction", min: -0.8, max: 0.5, needs_target: "a sector", reaches: "that sector" },
  ],
  reverse: { presets_pct: [-2, -5, -10], min_target_pct: -95, tolerance_pp: 0.02, method: "BOUNDED_GRID_MINIMAX", axes: [] },
  sectors: [{ value: "Energy", label: "Energy", detail: null }], issuers: [], currencies: [{ value: "EUR", label: "EUR", detail: null }], risk_factors: [],
} as unknown as LabOptions;

const att = {
  run_id: "run_1", version: "v", portfolio_id: "default", total_pnl: -108000, baseline_value: 1300000, pnl_pct: -0.083, headline: "Total modeled change -$108,000 (-8.31% of the portfolio): market-wide shocks -$108,000.",
  drivers: { dimension: "driver", label: "By kind of shock", rows: [{ key: "MARKET", label: "Market-wide shocks", delta: -108000, share_of_total: 1, baseline_value: 1300000, position_count: 4, detail: null }], total: -108000, sum: -108000, residual: 0, reconciled: true },
  tables: [], tolerance: 0.01, reconciled: true, note: "n", labels: [],
};

const result = (over: Partial<LabResult> = {}): LabResult =>
  ({
    version: "lab-v1", scenario_id: "scn_lab_abc123", scenario_type: "CUSTOM", name: "Mild sell-off", created_at: "2026-10-01T12:00:00Z", portfolio_id: "default", portfolio_name: "Synthetic book", status: "COMPLETED", reason: null,
    assumptions: [{ index: 0, origin: "USER", kind: "EQUITY_MARKET", label: "SCENARIO ASSUMPTION", description: "Equity market −10.0%", value: -0.1, unit: "fraction", target: null, target_label: null, rationale: "worried about it", shocks: [], reach: "APPLIED", positions_reached: 4, value_reached: 1200000, share_reached: 0.92, pnl: -108000, note: null },
      { index: 1, origin: "USER", kind: "COMMODITY", label: "SCENARIO ASSUMPTION", description: "Oil price −30.0%", value: -0.3, unit: "fraction", target: null, target_label: null, rationale: "", shocks: [], reach: "NOT_REACHED", positions_reached: 0, value_reached: 0, share_reached: 0, pnl: 0, note: "no position has an oil elasticity: switch on the sector-prior estimate to include one" }],
    result: { run_id: "run_1", status: "COMPLETED", signal_id: "scenario-lab", summary: { baseline_value: 1300000, stressed_value: 1192000, pnl: -108000, pnl_pct: -0.0831 }, positions: [], shocks: [] } as never,
    attribution: att as never, exposure_priors: [], history_check: null, provenance: [], label: "SCENARIO SIMULATION — NOT A PREDICTION", note: "A hypothetical stress analysis under the assumptions above. It is not a prediction, a forecast or an expected return.", labels: [], limitations: [], ...over,
  }) as LabResult;

describe("LabResultView", () => {
  it("shows before, after and change, labels every assumption, and says what reached nothing", () => {
    wrap(<LabResultView r={result()} />);
    expect(screen.getByText("SCENARIO SIMULATION — NOT A PREDICTION")).toBeInTheDocument();
    const g = screen.getByRole("group", { name: "Portfolio value before and after" });
    expect(within(g).getByText("$1.3M")).toBeInTheDocument();
    expect(within(g).getByText("$1.2M")).toBeInTheDocument();
    expect(within(g).getByText("−$108.0K")).toBeInTheDocument();
    expect(screen.getAllByText("SCENARIO ASSUMPTION")).toHaveLength(2);
    expect(screen.getByText("Reaches nothing")).toBeInTheDocument();
    expect(screen.getByText(/switch on the sector-prior estimate/)).toBeInTheDocument();
    expect(screen.getByText("worried about it")).toBeInTheDocument();
    expect(screen.getByText(/not a prediction, a forecast or an expected return/)).toBeInTheDocument();
  });

  it("marks an assessed scenario's assumptions as EventShock's, not the user's", () => {
    wrap(<LabResultView r={result({ scenario_type: "ASSESSED", assumptions: [{ ...result().assumptions[0], origin: "ASSESSED", kind: "ASSESSED_SHOCK" } as never] })} />);
    expect(screen.getByText(/EventShock's, not yours/)).toBeInTheDocument();
    expect(screen.queryByText("SCENARIO ASSUMPTION")).not.toBeInTheDocument();
  });

  it("explains a scenario that moved nothing instead of showing a zero", () => {
    wrap(<LabResultView r={result({ status: "NOT_APPLICABLE", reason: "No position in this portfolio carries the exposure these shocks act on", result: null, attribution: null })} />);
    expect(screen.getByText("Nothing in the portfolio was moved")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Portfolio value before and after" })).not.toBeInTheDocument();
  });

  it("discloses oil exposure that was estimated from priors", () => {
    wrap(<LabResultView r={result({ exposure_priors: [{ sector: "Energy", sensitivity: 0.8, positions: 3, value: 5e5, label: "JUDGEMENT PRIOR" }] })} />);
    expect(screen.getByText("Oil exposure was estimated, not measured.")).toBeInTheDocument();
    expect(screen.getByText(/Energy 0.80 on 3 positions/)).toBeInTheDocument();
  });
});

describe("CompareView", () => {
  const cmp = (): LabComparison => ({
    version: "lab-v1", portfolio_id: "default", portfolio_name: "Synthetic book", label: "SCENARIO SIMULATION — NOT A PREDICTION", note: "n", worst_scenario_id: "scn_b",
    results: [result({ name: "Base", scenario_id: "scn_a" }), result({ name: "Severe", scenario_id: "scn_b" })],
    rows: [
      { scenario_id: "scn_a", name: "Base", scenario_type: "BASE", status: "COMPLETED", baseline_value: 1300000, stressed_value: 1300000, pnl: 0, pnl_pct: 0, dominant_driver: null, top_sectors: [], top_risk_factors: [], top_holdings: [], assumption_count: 0 },
      { scenario_id: "scn_b", name: "Severe", scenario_type: "CUSTOM", status: "COMPLETED", baseline_value: 1300000, stressed_value: 1100000, pnl: -200000, pnl_pct: -0.1538, dominant_driver: "Market-wide shocks", top_sectors: ["Financials"], top_risk_factors: ["Equity market level"], top_holdings: ["JPMorgan Chase"], assumption_count: 1 },
    ],
    assumption_diff: [{ key: "EQUITY_MARKET||USER", label: "Equity Market", values: [null, "−20.0%"], differs: true }],
  }) as LabComparison;

  it("lays the scenarios side by side with the loss, the driver and what differs", () => {
    wrap(<CompareView c={cmp()} />);
    const t = screen.getByRole("table", { name: "Scenarios compared" });
    expect(within(t).getByText("Largest loss")).toBeInTheDocument();
    expect(within(t).getByText("Market-wide shocks")).toBeInTheDocument();
    expect(within(t).getByText("JPMorgan Chase")).toBeInTheDocument();
    const diff = screen.getByRole("table", { name: "The assumptions of each scenario" });
    expect(within(diff).getByText("Differs")).toBeInTheDocument();
    expect(screen.getByText("SCENARIO SIMULATION — NOT A PREDICTION")).toBeInTheDocument();
  });
});

function stub(opts: { lab?: boolean } = {}) {
  const calls: { url: string; body?: { scenarios?: unknown[]; scenario_type?: string; assumptions?: { value: number }[] } }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, body });
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { scenario_lab: opts.lab ?? true } });
    if (url.startsWith("/api/lab/options")) return json(options);
    if (url === "/api/scenarios/compare") return json({ ...cmpFixture() });
    if (url === "/api/scenarios") return json(result({ scenario_type: body.scenario_type }));
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}
const cmpFixture = () => ({ version: "lab-v1", portfolio_id: "default", portfolio_name: "Synthetic book", label: "x", note: "n", worst_scenario_id: null, results: [result({ name: "A" }), result({ name: "B" })], rows: [
  { scenario_id: "a", name: "A", scenario_type: "CUSTOM", status: "COMPLETED", baseline_value: 1, stressed_value: 1, pnl: 0, pnl_pct: 0, dominant_driver: null, top_sectors: [], top_risk_factors: [], top_holdings: [], assumption_count: 1 },
  { scenario_id: "b", name: "B", scenario_type: "BASE", status: "COMPLETED", baseline_value: 1, stressed_value: 1, pnl: 0, pnl_pct: 0, dominant_driver: null, top_sectors: [], top_risk_factors: [], top_holdings: [], assumption_count: 0 }], assumption_diff: [] });

describe("ScenarioLab", () => {
  it("is hidden where the lab is not served", async () => {
    stub({ lab: false });
    const { container } = wrap(<ScenarioLab />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("builds a scenario, converts the typed percentage to a fraction and shows the labelled result", async () => {
    const calls = stub();
    wrap(<ScenarioLab />);
    await screen.findByRole("heading", { name: /What if/ });
    const run = screen.getByRole("button", { name: "Run scenario" });
    const row = await screen.findByRole("listitem", { name: "Assumption 1" });
    expect(run).toBeDisabled();                                                   // a shock with no size cannot run
    expect(within(row).getByText("SCENARIO ASSUMPTION")).toBeInTheDocument();    // the label is on the row before anything runs
    await userEvent.type(within(row).getByLabelText(/size of assumption 1/i), "-10");
    expect(run).toBeEnabled();
    await userEvent.click(run);
    await screen.findByText("SCENARIO SIMULATION — NOT A PREDICTION");
    const post = calls.find((c) => c.url === "/api/scenarios");
    expect(post?.body).toMatchObject({ scenario_type: "CUSTOM", assumptions: [{ kind: "EQUITY_MARKET", value: -0.1 }] });
    expect(post?.body?.assumptions?.[0]?.value).toBeCloseTo(-0.1);
  });

  it("offers only the vocabulary for a target and warns when a currency shock cannot reach anything", async () => {
    stub();
    wrap(<ScenarioLab />);
    const row = await screen.findByRole("listitem", { name: "Assumption 1" });
    await userEvent.selectOptions(within(row).getByRole("combobox", { name: "Shock" }), "FX");
    const target = within(row).getByLabelText("Target of assumption 1");
    expect(within(target).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose…", "EUR"]);        // no free text for a subject
    expect(screen.getByText(/holds nothing in another currency/)).toBeInTheDocument();
  });

  it("limits the number of scenarios to what can be compared and compares them in one call", async () => {
    const calls = stub();
    wrap(<ScenarioLab signalId="sig_1" />);
    await screen.findByRole("heading", { name: /What if/ });
    await userEvent.click(screen.getByRole("button", { name: /add the base case/i }));
    expect(screen.getByRole("button", { name: /add the base case/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /add this event's assessed scenario/i }));
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a custom scenario/i })).toBeDisabled();
    await userEvent.type(await screen.findByLabelText(/size of assumption 1/i), "-5");
    await userEvent.click(screen.getByRole("button", { name: /run and compare 3/i }));
    await screen.findByRole("table", { name: "Scenarios compared" });
    const cmp = calls.find((c) => c.url === "/api/scenarios/compare");
    expect(cmp?.body?.scenarios).toHaveLength(3);
    expect((cmp?.body?.scenarios as { scenario_type: string }[]).map((s) => s.scenario_type)).toEqual(["CUSTOM", "BASE", "ASSESSED"]);
  });
});

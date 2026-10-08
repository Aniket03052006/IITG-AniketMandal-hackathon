import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AutoStressResult, ConcentrationView, GeneratedScenario, OverlapView, PortfolioMateriality, PropagationGraph, StressAttribution } from "../../api/types";
import { AttributionPanel } from "./AttributionPanel";
import { AutoScenarioCard } from "./AutoScenarioCard";
import { ConcentrationPanel } from "./ConcentrationPanel";
import { MaterialityPanel } from "./MaterialityPanel";
import { PropagationChain } from "./PropagationChain";
import { PropagationSection } from "./PropagationSection";

const wrap = (ui: React.ReactElement, path = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const materiality = (over: Partial<PortfolioMateriality> = {}): PortfolioMateriality =>
  ({
    signal_id: "s1", version: "propagation-v1", portfolio_id: "default", portfolio_name: "Synthetic book", availability: "AVAILABLE", reason: null, level: "HIGH", level_from_grid: "MEDIUM",
    exposure_row: "HIGH", severity_column: "HIGH", mapping_basis: "EVIDENCED_SCOPE", reached_share: 0.31, labels: ["Relevance to your holdings only: it is not a forecast of loss."], adjustments: null,
    why: ["It reaches 31.0% of the book (40 positions).", "Severity is 8 of 10, read from the high column: the grid says MEDIUM.", "one position is 55% of what is reached: the level goes up one step to HIGH"],
    summary: "HIGH: reaches 31.0% of the book.",
    components: [
      { id: "severity", label: "Event severity", display: "8 of 10", value: 8, band: "HIGH", detail: "the transparent severity scorecard (uncalibrated)" },
      { id: "reach", label: "Share of the book reached (counted once)", display: "31.0%", value: 0.31, band: "HIGH", detail: "40 positions" },
    ],
    rules: [
      { kind: "GRID", id: "grid.HIGH.HIGH", fired: true, effect: "high exposure with high severity gives MEDIUM" },
      { kind: "BUMP", id: "concentration_bump", fired: true, effect: "one position is 55% of what is reached: up one step" },
      { kind: "CAP", id: "assumption_only_cap", fired: false, effect: "applies only when no part of the reach is evidenced" },
    ],
    ...over,
  }) as PortfolioMateriality;

const graph = (over: Partial<PropagationGraph> = {}): PropagationGraph =>
  ({
    signal_id: "s1", version: "propagation-v1", availability: "AVAILABLE", reason: null, portfolio_id: "default", portfolio_name: "Synthetic book", event_category: "MACROECONOMIC",
    nodes: [
      { id: "event", kind: "EVENT", label: "Fed signals a rate hike", detail: "MACROECONOMIC", value: null, share: null },
      { id: "rf:RATES", kind: "RISK_FACTOR", label: "Interest rates", detail: "engine", value: null, share: null },
      { id: "target:ASSET_CLASS:BOND", kind: "ASSET_CLASS", label: "Bond positions", detail: "9 positions held", value: 1000, share: 0.2 },
      { id: "target:SECTOR:Technology", kind: "SECTOR", label: "Technology", detail: "5 positions held", value: 500, share: 0.1 },
      { id: "target:SECTOR:Healthcare", kind: "SECTOR", label: "Healthcare", detail: "3 positions held", value: 300, share: 0.06 },
      { id: "portfolio", kind: "PORTFOLIO", label: "Synthetic book", detail: null, value: 5000, share: 1 },
    ],
    edges: [
      { source: "event", target: "rf:RATES", relationship: "ABOUT", rule_id: "scope.theme_or_terms", basis: "the text says “rate hike”", status: "OBSERVED", weight: null },
      { source: "rf:RATES", target: "target:ASSET_CLASS:BOND", relationship: "SENSITIVE_TO", rule_id: "risk_factors.RATES.transmission.bonds_duration", basis: "Bond prices fall as yields rise.", status: "OBSERVED", weight: 1 },
      { source: "rf:RATES", target: "target:SECTOR:Technology", relationship: "ASSUMED_TRANSMISSION", rule_id: "risk_factors.RATES.transmission.tech_long_duration", basis: "Long-duration growth equities.", status: "SCENARIO_ASSUMPTION", weight: 0.5 },
      { source: "rf:RATES", target: "target:SECTOR:Healthcare", relationship: "ASSUMED_TRANSMISSION", rule_id: "risk_factors.RATES.transmission.user_health", basis: "my own view (adjusted by you)", status: "USER_ASSUMPTION", weight: 0.3 },
      { source: "target:ASSET_CLASS:BOND", target: "portfolio", relationship: "HELD_BY", rule_id: "holdings", basis: "9 position(s)", status: "OBSERVED", weight: null },
    ],
    active_factors: [{ id: "RATES", label: "Interest rates", modelled: "ENGINE", origin: "TEXT", status: "OBSERVED", evidence: ["the text says “rate hike”"], note: null }],
    reached: [{ asset_id: "b1", name: "Treasury 2030", entity_id: "E", asset_type: "BOND", sector: "Other", industry: null, geography: "US", market_value: 1000, share: 0.2, basis: "EVIDENCED_SCOPE", routes: ["RATES:bonds_duration"] }],
    reached_value: 1500, reached_share: 0.3, direct_share: 0, indirect_share: 0.3, evidenced_share: 0.2, assumed_share: 0.1, mapping_basis: "EVIDENCED_SCOPE", not_reached: ["Consumer: the book holds nothing in it"],
    labels: ["A mapping of how an event could reach holdings under stated assumptions. It is not causal inference."], limitations: [], adjustments: null,
    ...over,
  }) as PropagationGraph;

const scenario = (over: Partial<GeneratedScenario> = {}): GeneratedScenario =>
  ({
    signal_id: "s1", version: "propagation-v1", label: "SCENARIO SIMULATION — NOT A PREDICTION", availability: "AVAILABLE", reason: null, template: "MACROECONOMIC", template_label: "Macro rates shock",
    can_force: false, portfolio_id: "default", adjustments: null,
    gates: [{ id: "event", label: "The text describes a market event", passed: true, detail: "macroeconomic" }, { id: "severity", label: "Severity at least 7", passed: true, detail: "severity 8" }],
    scenario: { id: "gen_macroeconomic_ab12cd34", version: "gen-x", name: "Macro rates shock, generated for this event", category: "MACROECONOMIC", description: "d", illustrative: true, reference_impact: 7,
      shocks: [{ factor: "RATES_BPS", scope: "MARKET", value: 100, rationale: "", sector: null }, { factor: "EQUITY", scope: "SECTOR", value: -0.075, rationale: "", sector: "Technology" }] },
    origins: [
      { factor: "RATES_BPS", scope: "MARKET", sector: null, source: "CATALOG_BASE", risk_factor: null, status: "SCENARIO_ASSUMPTION", base_value: 100, basis: "catalog scenario" },
      { factor: "EQUITY", scope: "SECTOR", sector: "Technology", source: "PROPAGATED", risk_factor: "RATES", status: "USER_ASSUMPTION", base_value: -0.075, basis: "transmission weight +0.50" },
    ],
    history_check: null,
    ...over,
  }) as GeneratedScenario;

const attribution = (): StressAttribution => {
  const t = (dimension: string, label: string, rows: [string, string, number][]) => ({
    dimension, label, total: -100, sum: -100, residual: 0, reconciled: true,
    rows: rows.map(([key, l, delta]) => ({ key, label: l, delta, share_of_total: delta / -100, baseline_value: 1000, position_count: 2, detail: null })),
  });
  return {
    run_id: "run_1", version: "propagation-v1", portfolio_id: "default", total_pnl: -100, baseline_value: 5000, pnl_pct: -0.02, headline: "Total modeled change -$100 (-2.00% of the portfolio): market-wide -$60, sector -$40.",
    drivers: t("driver", "By kind of shock", [["MARKET", "Market-wide shocks", -60], ["SECTOR", "Sector shocks", -40]]),
    tables: [t("issuer", "By issuer", [["A", "Acme", -70], ["B", "Beta", -30]]), t("sector", "By sector", [["Tech", "Technology", -100]])],
    tolerance: 0.01, reconciled: true, note: "Each table is the same total regrouped.", labels: ["Not causal attribution and not a forecast."],
  } as unknown as StressAttribution;
};

describe("MaterialityPanel", () => {
  it("answers why the event matters: the level, the reasons in order, and the rule that fired", () => {
    render(<MemoryRouter><MaterialityPanel m={materiality()} /></MemoryRouter>);
    expect(screen.getByText(/Relevance: High/)).toBeInTheDocument();
    expect(screen.getAllByText(/reaches 31\.0% of the book/).length).toBeGreaterThan(0);
    expect(screen.getByText(/the grid says MEDIUM/)).toBeInTheDocument();
    const rules = screen.getByRole("list", { name: /rules applied in order/i, hidden: true });
    expect(within(rules).getByText(/Bump/)).toBeInTheDocument();
    expect(rules).toHaveTextContent(/Cap \(did not apply\)/);
  });

  it("says an unrelated portfolio is not relevant and an unmappable event cannot be stated", () => {
    const { rerender } = render(<MemoryRouter><MaterialityPanel m={materiality({ level: "NONE", reached_share: 0, why: ["You hold nothing it reaches."], summary: "Not relevant to this portfolio.", components: [], rules: [] })} /></MemoryRouter>);
    expect(screen.getByText(/Relevance: Not relevant/)).toBeInTheDocument();
    rerender(<MemoryRouter><MaterialityPanel m={materiality({ level: "UNDETERMINED", availability: "ABSTAINED", why: ["No defensible mapping."], summary: "Relevance cannot be stated: no defensible mapping.", components: [], rules: [] })} /></MemoryRouter>);
    expect(screen.getByText(/Relevance: Cannot be stated/)).toBeInTheDocument();
    expect(screen.queryByText(/reaches .* of the book/)).not.toBeInTheDocument();
  });

  it("marks values the user adjusted", () => {
    render(<MemoryRouter><MaterialityPanel m={materiality({ adjustments: { count: 2, paths: ["a", "b"], note: "adjusted" } })} /></MemoryRouter>);
    expect(screen.getByRole("button", { name: /2 adjusted by you/i })).toBeInTheDocument();
  });
});

describe("PropagationChain", () => {
  it("shows each edge with its rule, its basis and whether it is observed or assumed", () => {
    render(<MemoryRouter><PropagationChain g={graph()} /></MemoryRouter>);
    const edges = screen.getByRole("list", { name: /edges from the event/i });
    expect(within(edges).getAllByRole("listitem")).toHaveLength(3 + 1); // the three flow edges plus the user's
    expect(screen.getAllByText("Observed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Scenario assumption").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Your assumption").length).toBeGreaterThan(0);
    expect(within(edges).getByText(/risk_factors\.RATES\.transmission\.tech_long_duration/)).toBeInTheDocument(); // in the list (the map also carries it in a tooltip)
    expect(screen.getByText(/not causal inference/)).toBeInTheDocument();
  });

  it("lists the holdings reached and the targets with nothing held", () => {
    render(<MemoryRouter><PropagationChain g={graph()} /></MemoryRouter>);
    expect(screen.getByText("Treasury 2030")).toBeInTheDocument();
    expect(screen.getByText(/1 mapped target the book holds nothing in/)).toBeInTheDocument();
  });

  it("abstains in words when there is no defensible mapping", () => {
    render(<MemoryRouter><PropagationChain g={graph({ availability: "ABSTAINED", reason: "No defensible mapping: the text names nothing.", reached: [], nodes: [], edges: [], active_factors: [] })} /></MemoryRouter>);
    expect(screen.getByText("No defensible mapping to the portfolio")).toBeInTheDocument();
    expect(screen.getByText(/does not guess/)).toBeInTheDocument();
  });
});

describe("AutoScenarioCard", () => {
  it("always labels the scenario a simulation and says where each shock comes from", async () => {
    const onRun = vi.fn();
    render(<MemoryRouter><AutoScenarioCard gen={scenario()} onRun={onRun} running={false} ran={false} /></MemoryRouter>);
    expect(screen.getByRole("note")).toHaveTextContent("SCENARIO SIMULATION — NOT A PREDICTION");
    expect(screen.getByText("Catalog base")).toBeInTheDocument();
    expect(screen.getByText("Propagated")).toBeInTheDocument();
    expect(screen.getByText("Your assumption")).toBeInTheDocument(); // the propagated shock rests on an edge the user adjusted
    await userEvent.click(screen.getByRole("button", { name: /run on my portfolio/i }));
    expect(onRun).toHaveBeenCalledWith(false);
  });

  it("says SCENARIO UNAVAILABLE with the failed condition, and offers a what-if only for a soft gate", async () => {
    const onRun = vi.fn();
    const soft = scenario({ availability: "ABSTAINED", can_force: true, reason: "SCENARIO UNAVAILABLE: Severity at least 7 (severity 5). It can be run as a what-if.",
      gates: [{ id: "severity", label: "Severity at least 7", passed: false, detail: "severity 5" }] });
    const { rerender } = render(<MemoryRouter><AutoScenarioCard gen={soft} onRun={onRun} running={false} ran={false} /></MemoryRouter>);
    expect(screen.getByText("SCENARIO UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getAllByText(/severity 5/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /run as a what-if anyway/i }));
    expect(onRun).toHaveBeenCalledWith(true);
    rerender(<MemoryRouter><AutoScenarioCard gen={scenario({ availability: "UNAVAILABLE", can_force: false, scenario: null, origins: [], reason: "SCENARIO UNAVAILABLE: the book holds nothing the event reaches.",
      gates: [{ id: "mapping", label: "A defensible mapping exists", passed: false, detail: "nothing is reached" }] })} onRun={onRun} running={false} ran={false} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: /run/i })).not.toBeInTheDocument();
    expect(screen.getByText(/holds nothing the event reaches/)).toBeInTheDocument();
  });
});

describe("AttributionPanel", () => {
  it("states the total, shows every dimension and says the rows add up to it", async () => {
    render(<MemoryRouter><AttributionPanel att={attribution()} /></MemoryRouter>);
    expect(screen.getByText(/Total modeled change -\$100/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/rows add up to .*100.*total change is .*100.*difference 0\.00/);
    await userEvent.click(screen.getByRole("tab", { name: "Issuer" }));
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText(/Not causal attribution/)).toBeInTheDocument();
  });
});

describe("ConcentrationPanel", () => {
  const view = {
    portfolio_id: "default", portfolio_name: "Synthetic book", version: "v", total_value: 5000, note: "Only meaningful concentration is flagged.", adjustments: null,
    flags: ["Sector Financials: 31% of the book, 1.9 times an equal split across 6 sectors."],
    dimensions: [{ dimension: "sector", label: "Sector", item_count: 6, hhi: 0.2, effective_n: 5, top_share: 0.31, flagged: true, reason: null, note: null,
      rows: [{ key: "Financials", label: "Financials", value: 1550, share: 0.31, position_count: 8, flagged: true }, { key: "Energy", label: "Energy", value: 500, share: 0.1, position_count: 3, flagged: false }] }],
  } as unknown as ConcentrationView;
  const overlaps = (clusters: OverlapView["clusters"]): OverlapView => ({ portfolio_id: "default", version: "v", availability: "AVAILABLE", reason: clusters.length ? null : "no risk factor is borne on by several independent events", window_days: 7, considered: 12, clusters, note: "Events from the last 7 days.", adjustments: null }) as OverlapView;

  it("flags only meaningful concentration, in words", () => {
    render(<MemoryRouter><ConcentrationPanel view={view} /></MemoryRouter>);
    expect(screen.getByRole("list", { name: /meaningful concentration/i })).toHaveTextContent(/1\.9 times an equal split/);
    expect(screen.getByText("flagged")).toBeInTheDocument();
  });

  it("draws overlapping events as one concentrated risk through the shared factor and holdings", () => {
    const cluster = { risk_factor: "RATES", risk_factor_label: "Interest rates", shared_value: 1200, shared_share: 0.24,
      sentence: "2 independent events bear on interest rates and reach the same 9 positions (24.0% of the book): the risk is concentrated in those holdings.",
      events: [{ signal_id: "a", event_id: "e1", headline: "Fed hikes", published_at: null, materiality: "HIGH", severity: 8 }, { signal_id: "b", event_id: "e2", headline: "Yields jump", published_at: null, materiality: "MEDIUM", severity: 7 }],
      shared_holdings: [{ asset_id: "x", name: "Treasury 2030", entity_id: "E", asset_type: "BOND", sector: "Other", industry: null, geography: "US", market_value: 1200, share: 0.24, basis: "EVIDENCED_SCOPE", routes: [] }] };
    render(<MemoryRouter><ConcentrationPanel view={view} overlaps={overlaps([cluster] as OverlapView["clusters"])} /></MemoryRouter>);
    expect(screen.getByText("Concentrated risk: Interest rates")).toBeInTheDocument();
    expect(screen.getByText("Fed hikes")).toBeInTheDocument();
    expect(screen.getByText(/the same risk factor ↓ the same holdings/)).toBeInTheDocument();
  });

  it("says plainly when nothing overlaps", () => {
    render(<MemoryRouter><ConcentrationPanel overlaps={overlaps([])} /></MemoryRouter>);
    expect(screen.getByText(/no risk factor is borne on by several independent events/)).toBeInTheDocument();
  });
});

describe("PropagationSection", () => {
  const flow = { signal_id: "s1", version: "v", portfolio_id: "default", portfolio_name: "Synthetic book", graph: graph(), materiality: materiality(), scenario: scenario(), existing_run_id: null, adjustments: null };
  const completed = {
    signal_id: "s1", version: "v", portfolio_id: "default", materiality: materiality(), scenario: scenario(), note: null, adjustments: null, attribution: attribution(),
    chain: { summary: "The largest modeled effect is the sector equity price shock.", total_impact: -100 },
    run: { run_id: "run_1", status: "COMPLETED", reason: null, summary: { baseline_value: 5000, stressed_value: 4900, pnl: -100, pnl_pct: -0.02 }, audit: { forced: false } },
  } as unknown as AutoStressResult;

  const stub = (propagation: boolean) => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/meta")) return json({ capabilities: { propagation } });
      if (url.includes("/portfolio-stress")) return json(completed);
      if (url.includes("/propagation")) return json(flow);
      if (url.startsWith("/api/concentration/overlaps")) return json({ portfolio_id: "default", version: "v", availability: "AVAILABLE", reason: "none", window_days: 7, considered: 0, clusters: [], note: "n", adjustments: null });
      if (url.startsWith("/api/concentration")) return json({ portfolio_id: "default", portfolio_name: "x", version: "v", total_value: 1, dimensions: [], flags: [], note: "n", adjustments: null });
      return json({ detail: "nope" }, 404);
    }));
    return calls;
  };

  it("walks from why it matters to why the portfolio moved", async () => {
    const calls = stub(true);
    wrap(<PropagationSection signalId="s1" />);
    await screen.findByText(/Relevance: High/);
    expect(screen.getByText("My exposure: event → risk factor → holdings")).toBeInTheDocument();
    expect(screen.getByText("SCENARIO SIMULATION — NOT A PREDICTION")).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("POST") && c.includes("portfolio-stress"))).toBe(false); // nothing is run until asked
    await userEvent.click(screen.getByRole("button", { name: /run on my portfolio/i }));
    await screen.findByLabelText("Portfolio impact");
    expect(screen.getByText(/Total modeled change -\$100/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open the stress lab/i })).toHaveAttribute("href", "/stress?signal=s1");
    await waitFor(() => expect(calls.some((c) => c.includes("/portfolio-stress"))).toBe(true));
  });

  it("renders nothing where the capability is off", async () => {
    stub(false);
    const { container } = wrap(<PropagationSection signalId="s1" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(container).toBeEmptyDOMElement();
  });
});

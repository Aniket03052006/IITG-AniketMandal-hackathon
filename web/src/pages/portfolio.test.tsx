import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSignalRelevance } from "../api/hooks";
import { PortfolioSwitcher } from "../components/portfolio/PortfolioSwitcher";
import { getActivePortfolio, resetActivePortfolioForTests, setActivePortfolio } from "../lib/portfolio";
import { PortfolioEditorPage } from "./PortfolioEditorPage";
import { PortfoliosPage } from "./PortfoliosPage";
import { StressPage } from "./StressPage";

const AS_OF = "2026-10-01T12:00:00Z";
const MINE = "pf_mine000001";
const items = [
  { id: "default", name: "Synthetic book", kind: "DEFAULT", base_currency: "USD", total_value: 860_000_000, holding_count: 103, description: "SYNTHETIC", updated_at: null },
  { id: MINE, name: "My core", kind: "USER", base_currency: "INR", total_value: 1_000_000, holding_count: 5, description: "Your portfolio", updated_at: AS_OF },
];

const audit = { mode: "REPLAY", data_origin: "DEMO_FIXTURE", engine_version: "1.0.0", scenario_version: "1.0", portfolio_id: MINE, portfolio_hash: "abc", threshold: 7, forced: false, impact_overridden: false, calculated_at: AS_OF, calculation: "deterministic engine" };
const completed = {
  run_id: "run_p1", status: "COMPLETED", reason: null, signal_id: "sig_2",
  scenario: { id: "scn_ops", version: "1.0", name: "Product / operations disruption", category: "PRODUCT_OPERATIONS", illustrative: true },
  severity: { impact_used: 7, reference_impact: 7, min_scale: 0.5, max_scale: 1.5, raw_ratio: 1, scale: 1, formula: "scale = 1.0000" },
  shocks: [{ factor: "EQUITY", scope: "MARKET", base_value: -0.1, scaled_value: -0.1, applicable: true, rationale: "" }],
  summary: { baseline_value: 1_000_000, stressed_value: 961_500, pnl: -38_500, pnl_pct: -0.0385 },
  positions: [{ asset_id: "H001-AAPL", name: "Apple", asset_class: "EQUITY", entity_id: "ENT_AAPL", sector: "Technology", baseline_value: 400_000, stressed_value: 361_500, delta: -38_500, delta_pct: -0.09625, shocks: [{ factor: "EQUITY", scope: "MARKET", value: -0.1 }], by_factor: { EQUITY: -38_500 }, formula: "dV = V x beta x s" }],
  contributions: {
    by_asset_class: [{ key: "EQUITY", label: "EQUITY", baseline_value: 400_000, delta: -38_500, share_of_loss: 1 }],
    by_sector: [{ key: "Technology", label: "Technology", baseline_value: 400_000, delta: -38_500, share_of_loss: 1 }],
    by_entity: [{ key: "ENT_AAPL", label: "Apple", baseline_value: 400_000, delta: -38_500, share_of_loss: 1 }],
    by_factor: [{ key: "EQUITY", label: "EQUITY", baseline_value: 0, delta: -38_500, share_of_loss: 1 }],
    top_positions: [{ key: "H001-AAPL", label: "Apple", baseline_value: 400_000, delta: -38_500, share_of_loss: 1 }],
  },
  uncovered: { asset_count: 0, market_value: 0, share_of_portfolio: 0, asset_ids: [] },
  audit,
};
const chain = {
  run_id: "run_p1", portfolio_id: MINE, portfolio_name: "My core", event_line: "Market-wide event (rates)", scope_level: "MARKET",
  steps: [{ factor: "EQUITY", factor_label: "equity price shock", scope: "MARKET", scope_label: "market-wide", applied_shock: -0.1, unit: "fraction", exposed_value: 400_000, exposed_share: 0.4, position_count: 1, sensitivity: "value-weighted beta 0.96", impact: -38_500, impact_pct: -0.0385, sentence: "" }],
  skipped: [], not_reached: { key: "unmoved", label: "Holdings this scenario does not move", market_value: 600_000, share: 0.6, position_count: 2 },
  total_impact: -38_500, total_impact_pct: -0.0385, summary: "The largest modeled effect is the market-wide equity price shock.", note: "A modeled scenario change, not a forecast.",
};
const sig = {
  id: "sig_2",
  document: { id: "d", source: "Wire", source_type: "NEWS", published_at: "2026-10-01T08:30:00Z", ingested_at: "2026-10-01T08:31:00Z", author: null, headline: "Rates jump", body: "b", url: "https://x.invalid", language: "en", raw_metadata: {} },
  entity: { entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, country: null, link_confidence: 0 },
  scope: { level: "MARKET", sector: null, regions: [], themes: ["rates"], basis: "THEME_TERMS", strength: null, matched_terms: {}, note: "", resolver_version: "x" },
  sentiment: { positive: 0.1, neutral: 0.1, negative: 0.8, score: -0.7 },
  event: { category: "MACROECONOMIC", status: "CLASSIFIED", no_event_probability: null, probabilities: { MACROECONOMIC: 0.8 } },
  impact: { score: 8, raw: 0.8, drivers: [], quantisation: "" }, evidence: { source_count: 1, unique_domain_count: 1, recent_mention_count: 0, coverage_velocity: 0, novelty_score: 0.5, novelty_measured: true, model_confidence: 0.8, contradicted_by: [], corroborating: [] },
  status: "COMPLETE", status_reason: null, data_origin: "DEMO_FIXTURE", model_versions: { sentiment: "f", event: "f", impact: "f", entity_resolver: "f", feature_schema: "1" }, created_at: AS_OF,
};
const rel = (band: string) => ({ signal_id: "sig_2", scope_level: "MARKET", level: "MARKET_WIDE", share: 0.4, summary: "A market-wide event.", path: [], slices: [], reach: null, band, portfolio_id: MINE, portfolio_name: "My core" });
const resolved = (ok: boolean) => ({
  ok, mode: "WEIGHT", total_value: 1_000_000, base_currency: "USD", portfolio: null,
  holdings: [{ index: 0, asset_id: "H001-AAPL", ticker: "AAPL", name: "Apple Inc.", asset_class: "EQUITY", sector: "Technology", region: "US", currency: "USD", value: 600_000, weight: 0.6, quantity: null, price: null, cost_basis: null, unrealised_pnl: null, beta: 1.2, duration: null, spread_sensitivity: null, in_universe: true, sources: { beta: "REFERENCE" }, basis: [] }],
  issues: ok ? [] : [{ level: "ERROR", code: "WEIGHTS_SUM", message: "The weights add up to 60.00%, not 100%: add the rest.", holding: null, field: "weight_pct" }],
});

let calls: { url: string; init?: RequestInit }[] = [];
let validateOk = true;
let assessedSeverity: number | null = null; // when set, the assessment layer is on and says this (the trained impact on the signal stays 3)
let listing = items;

function mockFetch() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      const path = url.replace(/^.*\/api/, "");
      if (path === "/meta") return json({ app: "EventShock", version: "0", mode: "REPLAY", profile: "demo", replay: null, data_origin: "DEMO_FIXTURE", as_of: AS_OF, trigger_threshold: 7, base_currency: "USD", signal_count: 1, asset_count: 3, scenario_set_version: "1", engine_version: "1", notices: [], capabilities: { analyze: false, live_enabled: false, assessment: assessedSeverity !== null }, taxonomy: [{ id: "MACROECONOMIC", label: "Macro", description: "", default_scenario: "scn_ops" }] });
      if (init?.method === "DELETE") return new Response(null, { status: 204 });
      if (path === "/portfolios" && init?.method === "POST") return json({ id: MINE, kind: "USER", stored: null, resolved: null, list_item: items[1] }, 201);
      if (path === "/portfolios") return json(listing);
      if (path === "/portfolios/validate") return json(resolved(validateOk));
      if (path === "/portfolios/parse") {
        const text = JSON.parse(String(init?.body)).text as string;
        if (text.includes("lots")) return json({ draft: null, issues: [{ level: "ERROR", code: "UNREADABLE_LINE", message: "Line 1: 'AAPL lots' - add a percent.", holding: 0, field: null }], resolved: null });
        return json({ draft: { name: "My portfolio", base_currency: "USD", mode: "WEIGHT", total_value: null, remainder_as_cash: false, notes: "", holdings: [{ ticker: "AAPL", name: null, weight_pct: 60, quantity: null, price: null, cost_basis: null, asset_class: null, sector: null, region: null, currency: null, beta: null, duration: null }] }, issues: [], resolved: resolved(false) });
      }
      if (path.startsWith("/portfolios/") && path.endsWith("/exposure")) return json({ portfolio_id: MINE, name: "My core", kind: "USER", base_currency: "INR", total_value: 1_000_000, position_count: 5, by_asset_class: [], by_sector: [], by_region: [], by_issuer: [], split: [], largest_positions: [], metrics: [], not_stressed: [], notes: [] });
      if (path.startsWith("/portfolio/summary")) return json({ portfolio_id: MINE, name: "My core", description: "d", as_of: AS_OF, base_currency: "INR", total_value: 1_000_000, asset_count: 5, entity_count: 4, synthetic: false, kind: "USER" });
      if (path.startsWith("/portfolio/exposure")) return json({ by_asset_class: [], by_sector: [], by_entity: [], by_geography: [] });
      if (path.startsWith("/signals?") || path === "/signals") return json({ total: 1, seq: 0, items: [{ id: "sig_2", headline: "Rates jump", source: "Wire", source_type: "NEWS", published_at: AS_OF, entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, category: "MACROECONOMIC", event_status: "CLASSIFIED", sentiment_score: -0.7, impact_score: 8, status: "COMPLETE", source_count: 1, data_origin: "DEMO_FIXTURE", scope_level: "MARKET", scope_sector: null, scope_strength: null, scope_themes: ["rates"], scope_regions: [], channel: "REPLAY", first_seq: null, updated_seq: null, relevance_level: "MARKET_WIDE", relevance_share: 0.4, relevance_band: "HIGH" }] });
      if (path.includes("/relevance")) return json(rel(url.includes("portfolio_id") ? "HIGH" : "MEDIUM"));
      if (path.endsWith("/assessment") && assessedSeverity !== null) return json({ reading: { event_type: "MACROECONOMIC" }, severity: { score: assessedSeverity, low: assessedSeverity, high: assessedSeverity, band: "high", band_label: "High" }, severity_note: null, threshold: null });
      if (path.startsWith("/signals/")) return json({ ...sig, impact: { ...sig.impact, score: assessedSeverity === null ? 8 : 3 } });
      if (path === "/scenarios") return json({ version: "1", default_by_category: { MACROECONOMIC: "scn_ops" }, scenarios: [{ id: "scn_ops", version: "1.0", name: "Product / operations disruption", category: "MACROECONOMIC", description: "", illustrative: true, reference_impact: 7, shocks: [] }] });
      if (path === "/stress-test" && init?.method === "POST") return json(completed);
      if (path.endsWith("/exposure-chain")) return json(chain);
      return json({ detail: "not found" }, 404);
    }),
  );
}

function wrap(path: string, ui: React.ReactNode, routePath = "*") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={routePath} element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  resetActivePortfolioForTests();
  validateOk = true;
  assessedSeverity = null;
  listing = items;
  mockFetch();
});
afterEach(() => vi.unstubAllGlobals());

describe("portfolio switcher: optional, and always one click back to the default", () => {
  it("starts on the default and lists saved portfolios", async () => {
    wrap("/", <PortfolioSwitcher />);
    const select = await screen.findByRole("combobox", { name: "Portfolio to use" });
    await screen.findByRole("option", { name: "My core" });
    expect((select as HTMLSelectElement).value).toBe("default");
    expect(screen.getByText("Default · synthetic")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use default portfolio" })).toBeNull();
    expect(getActivePortfolio()).toBeNull();
  });

  it("switches to a personal portfolio, remembers it, and goes back with one click", async () => {
    wrap("/", <PortfolioSwitcher />);
    const select = await screen.findByRole("combobox", { name: "Portfolio to use" });
    await screen.findByRole("option", { name: "My core" });
    await userEvent.selectOptions(select, MINE);
    expect(getActivePortfolio()).toBe(MINE);
    expect(window.localStorage.getItem("eventshock-portfolio")).toBe(MINE);
    expect(await screen.findByText("Your portfolio")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Use default portfolio" }));
    expect(getActivePortfolio()).toBeNull();
    expect(window.localStorage.getItem("eventshock-portfolio")).toBeNull();
    expect(await screen.findByText("Default · synthetic")).toBeInTheDocument();
  });

  it("falls back to the default when the stored portfolio no longer exists", async () => {
    setActivePortfolio("pf_gone000001");
    wrap("/", <PortfolioSwitcher />);
    await waitFor(() => expect(getActivePortfolio()).toBeNull());
  });
});

function Probe({ id }: { id: string }) {
  const { data } = useSignalRelevance(id);
  return <p>{data ? `band ${data.band}` : "loading"}</p>;
}

describe("requests follow the active portfolio, and a default request is unchanged", () => {
  it("adds portfolio_id to relevance only when a personal portfolio is chosen", async () => {
    wrap("/", <Probe id="sig_2" />);
    expect(await screen.findByText("band MEDIUM")).toBeInTheDocument();
    expect(calls.find((c) => c.url.includes("/relevance"))?.url).toBe("/api/signals/sig_2/relevance");
    setActivePortfolio(MINE);
    wrap("/", <Probe id="sig_2" />);
    expect(await screen.findByText("band HIGH")).toBeInTheDocument();
    expect(calls.some((c) => c.url.includes(`/relevance?portfolio_id=${MINE}`))).toBe(true);
  });
});

describe("portfolio editor", () => {
  it("reads quick text into the detailed rows and shows what was understood", async () => {
    validateOk = false;
    wrap("/portfolios/new", <PortfolioEditorPage />, "/portfolios/:id");
    await userEvent.type(await screen.findByLabelText("Holdings, one per line"), "AAPL 60%");
    await userEvent.click(screen.getByRole("button", { name: /Read these holdings/ }));
    expect(await screen.findByLabelText("Ticker 1")).toHaveValue("AAPL");
    expect(await screen.findByText(/The weights add up to 60.00%, not 100%/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save portfolio" })).toBeDisabled();
  });

  it("says which line could not be read", async () => {
    wrap("/portfolios/new", <PortfolioEditorPage />, "/portfolios/:id");
    await userEvent.type(await screen.findByLabelText("Holdings, one per line"), "AAPL lots");
    await userEvent.click(screen.getByRole("button", { name: /Read these holdings/ }));
    expect(await screen.findByText("Some lines could not be read")).toBeInTheDocument();
    expect(screen.getByText(/add a percent/)).toBeInTheDocument();
  });

  it("saves a valid portfolio and makes it the one in use", async () => {
    wrap("/portfolios/new", <PortfolioEditorPage />, "/portfolios/:id");
    await userEvent.type(await screen.findByLabelText("Holdings, one per line"), "AAPL 60%");
    await userEvent.click(screen.getByRole("button", { name: /Read these holdings/ }));
    const save = await screen.findByRole("button", { name: "Save portfolio" });
    await waitFor(() => expect(save).toBeEnabled());
    await userEvent.click(save);
    await waitFor(() => expect(getActivePortfolio()).toBe(MINE));
    const post = calls.find((c) => c.url.endsWith("/api/portfolios") && c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body)).holdings[0]).toMatchObject({ ticker: "AAPL", weight_pct: 60 });
  });
});

describe("portfolios page", () => {
  it("explains that it is optional and offers the way back", async () => {
    setActivePortfolio(MINE);
    wrap("/portfolios", <PortfoliosPage />);
    expect(await screen.findByText("You are using your own portfolio")).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Use default portfolio" })[0]!);
    expect(getActivePortfolio()).toBeNull();
    expect(await screen.findByText("Optional. EventShock stresses a synthetic wholesale-banking book unless you choose a portfolio of your own.")).toBeInTheDocument();
  });

  it("asks before deleting and clears the choice when the active portfolio is deleted", async () => {
    setActivePortfolio(MINE);
    wrap("/portfolios", <PortfoliosPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByText(/Delete “My core”\?/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(getActivePortfolio()).toBeNull());
    expect(calls.some((c) => c.init?.method === "DELETE" && c.url.endsWith(`/api/portfolios/${MINE}`))).toBe(true);
  });
});

describe("stress page with a personal portfolio", () => {
  it("sends the portfolio, shows the three separate answers and the exposure chain", async () => {
    setActivePortfolio(MINE);
    wrap("/stress?signal=sig_2&run=1", <StressPage />);
    expect(await screen.findByText("Why is my portfolio exposed?")).toBeInTheDocument();
    const post = calls.find((c) => c.url.endsWith("/api/stress-test"));
    expect(JSON.parse(String(post?.init?.body)).portfolio_id).toBe(MINE);
    expect(screen.getByText("Event severity")).toBeInTheDocument();
    expect(screen.getByText("Portfolio relevance")).toBeInTheDocument();
    expect(screen.getByText("Modeled portfolio impact")).toBeInTheDocument();
    expect(await screen.findByText(/value-weighted beta 0.96/)).toBeInTheDocument();
    expect(screen.getAllByText(/not a forecast/i).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: "Use default portfolio" }).length).toBeGreaterThan(0);
  });

  it("starts the what-if slider at the assessed severity, not at the trained model's impact that arrives first", async () => {
    assessedSeverity = 8;
    wrap("/stress?signal=sig_2&run=1", <StressPage />);
    const slider = await screen.findByRole("slider", { name: /Impact score applied/ });
    await waitFor(() => expect((slider as HTMLInputElement).value).toBe("8"));
    expect(screen.queryByText(/What-if severity/)).toBeNull();
  });

  it("sends no portfolio at all on the default, exactly as before", async () => {
    wrap("/stress?signal=sig_2&run=1", <StressPage />);
    await screen.findByText("Event severity");
    const post = calls.find((c) => c.url.endsWith("/api/stress-test"));
    expect("portfolio_id" in JSON.parse(String(post?.init?.body))).toBe(false);
    expect(screen.queryByRole("button", { name: "Use default portfolio" })).toBeNull();
  });
});

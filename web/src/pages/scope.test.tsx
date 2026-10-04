import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ScopeTab } from "../components/scope/ScopeTab";
import { subjectLine } from "../lib/scope";
import { AnalyzePage, EXAMPLES } from "./AnalyzePage";
import { EventPage } from "./EventPage";
import { FeedPage } from "./FeedPage";
import { StressPage } from "./StressPage";

const AS_OF = "2026-10-01T12:00:00Z";

const meta = {
  app: "EventShock", version: "0.1.0", mode: "REPLAY", profile: "replay", data_origin: "REAL_SOURCE_MIXED_NLP", as_of: AS_OF,
  trigger_threshold: 7, base_currency: "USD", signal_count: 3, asset_count: 3, scenario_set_version: "1", engine_version: "1.0.0", notices: [],
  replay: { snapshot_id: "s", description: "d", window_start: "2026-09-17T00:00:00Z", window_end: "2026-09-30T23:59:59Z", output_digest: "ab".repeat(32), pipeline_version: "pipeline-2.0", stage_origins: {}, sources: ["gdelt-doc"] },
  taxonomy: [
    { id: "MACROECONOMIC", label: "Macroeconomic", description: "", default_scenario: "scn_macro" },
    { id: "MA_CORPORATE_ACTION", label: "M&A", description: "", default_scenario: "scn_ma" },
  ],
  impact: null, capabilities: { analyze: true, live_enabled: true },
};

const row = (over: object) => ({
  id: "sig_c", headline: "Meridian flags funding gap", source: "wire", source_type: "NEWS", published_at: "2026-10-01T08:30:00Z",
  entity_id: "ENT_M", entity_name: "Meridian Bancorp", ticker: "MRDB", sector: "Financials", category: "MACROECONOMIC", event_status: "CLASSIFIED",
  sentiment_score: -0.5, impact_score: 8, impact_origin: "MODEL", impact_lifecycle: "CALIBRATED", impact_score_low: null, impact_score_high: null,
  status: "COMPLETE", source_count: 1, data_origin: "REAL_SOURCE_MIXED_NLP", scope_level: "COMPANY", scope_sector: "Financials", scope_strength: null,
  scope_themes: [], scope_regions: ["US"], channel: "REPLAY", first_seq: null, updated_seq: null, relevance_level: "DIRECT", relevance_share: 0.05, ...over,
});

const sectorRow = row({
  id: "sig_s", headline: "Chipmakers slide as semiconductor demand softens", entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null,
  scope_level: "SECTOR", scope_sector: "Technology", scope_strength: "STRONG", relevance_level: "SECTOR", relevance_share: 0.13, channel: "MANUAL",
  first_seq: 3, updated_seq: 3,
});
const marketRow = row({
  id: "sig_m", headline: "Fed signals rate cuts", entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, scope_level: "MARKET",
  scope_sector: null, scope_themes: ["rates"], relevance_level: "MARKET_WIDE", relevance_share: 1, channel: "LIVE", first_seq: 5, updated_seq: 7,
});

const scopeOf = (over: object) => ({ level: "COMPANY", sector: "Financials", regions: ["US"], themes: [], basis: "ENTITY_RESOLVER", strength: null, matched_terms: {}, note: "n", resolver_version: "scope-v1", ...over });
const detail = (scope: object, entity: object) => ({
  id: "sig_x",
  document: { id: "d", source: "wire", source_type: "NEWS", published_at: "2026-10-01T08:30:00Z", ingested_at: "2026-10-01T08:31:00Z", author: null, headline: "Chipmakers slide", body: "", url: null, language: "en", raw_metadata: {} },
  entity, scope,
  sentiment: { positive: 0.1, neutral: 0.2, negative: 0.7, score: -0.6 },
  event: { category: "MACROECONOMIC", status: "CLASSIFIED", no_event_probability: null, probabilities: { MACROECONOMIC: 0.7, GEOPOLITICAL: 0.05, CREDIT_FUNDING: 0.05, MA_CORPORATE_ACTION: 0.05, REGULATORY_LEGAL: 0.05, PRODUCT_OPERATIONS: 0.04, EARNINGS_FINANCIAL_PERFORMANCE: 0.03, MARKET_VALUATION: 0.03 } },
  impact: { score: 8, raw: 0.8, drivers: [], quantisation: "q" },
  evidence: { source_count: 1, unique_domain_count: 1, recent_mention_count: 0, coverage_velocity: 0, novelty_score: 1, novelty_measured: false, model_confidence: 0.7, contradicted_by: [], corroborating: [] },
  status: "COMPLETE", status_reason: null, data_origin: "REAL_SOURCE_MIXED_NLP",
  model_versions: { sentiment: "s", event: "e", impact: "i", entity_resolver: "r", feature_schema: "1" }, created_at: AS_OF,
});
const noEntity = { entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, country: null, link_confidence: 0 };

const liveStatus = (over: object = {}) => ({
  enabled: true, state: "OK", source_mode: "GDELT", simulated: false, poll_interval_seconds: 300, last_attempt_at: AS_OF, last_success_at: AS_OF, next_attempt_at: AS_OF,
  last_error: null, consecutive_failures: 0, fetched_total: 10, new_total: 4, updated_total: 1, quarantined_total: 5, live_signal_count: 2, seq: 7, retention_hours: 48,
  event_model: "tfidf-lr-event-v1", event_model_note: "the served event model needs an encoder that is not installed", market_context_through: "2026-10-01", ...over,
});

const relevance = (over: object = {}) => ({
  signal_id: "sig_x", scope_level: "SECTOR", level: "SECTOR", share: 0.13, summary: "No single company is named; the event is about Technology, which is 13.0% of the book.",
  path: ["Technology sector: 13.0% of the book in 22 positions"],
  slices: [{ kind: "SECTOR", key: "Technology", label: "Technology", market_value: 7_000_000, share: 0.13, asset_count: 22, by_asset_class: { EQUITY: 1 } }],
  reach: { scenario_id: "scn_macro", scenario_name: "Macro rates shock", shocks_total: 4, shocks_bound: 1, note: "3 shock(s) need a company or sector this event does not name" }, ...over,
});

const analyzed = (over: object = {}) => ({
  outcome: "NEW", signal_id: "sig_s", signal: sectorRow, rejection: null, headline: sectorRow.headline, analysed_chars: 60, truncated: false,
  notes: ["Event type was scored by the reference model tfidf-lr-event-v1: no encoder."], ...over,
});

let state: Record<string, unknown>;
const calls: { url: string; body?: string }[] = [];

beforeEach(() => {
  calls.length = 0;
  state = {
    meta, feed: { total: 3, seq: 7, items: [row({}), sectorRow, marketRow] }, live: liveStatus(), analyze: analyzed(), detail: detail(scopeOf({}), {}),
    relevance: relevance(), stress: null,
    scenarios: { version: "1", default_by_category: { MACROECONOMIC: "scn_macro" }, scenarios: [{ id: "scn_macro", version: "1", name: "Macro rates shock", category: "MACROECONOMIC", description: "d", illustrative: true, reference_impact: 7, shocks: [] }] },
    scope: {
      version: "scope-v1", rules: ["A resolved company is the scope (COMPANY)."], sectors: { Energy: 3 }, themes: { rates: 2, trade_and_conflict: 1 }, regions: ["GB", "US"],
      replay_mix: { COMPANY: 10, SECTOR: 2, MARKET: 3, UNRESOLVED: 5 }, live_mix: {},
      evaluation: { snapshot_id: "s", single_issuer_documents: 100, vocabulary_fired: 27, coverage: 0.27, by_strength: { STRONG: { predicted: 30, correct: 27, precision: 0.9 }, WEAK: { predicted: 387, correct: 314, precision: 0.81 } }, per_sector: { Energy: { documents: 12, recall: 0.36, precision: 0.83 } }, limits: ["an optimistic proxy for the no-company case"] },
    },
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body as string | undefined });
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/meta")) return json(state.meta);
    if (url.includes("/api/signals?") || url.endsWith("/api/signals")) return json(state.feed);
    if (url.endsWith("/api/live/status")) return json(state.live);
    if (url.endsWith("/api/live/refresh")) return json(state.live);
    if (url.endsWith("/api/analyze")) return state.analyze instanceof Error ? json({ detail: state.analyze.message }, 503) : json(state.analyze);
    if (url.endsWith("/relevance")) return json(state.relevance);
    if (url.endsWith("/context")) return json({ detail: "none" }, 404);
    if (url.includes("/api/signals/")) return json(state.detail);
    if (url.endsWith("/api/scenarios")) return json(state.scenarios);
    if (url.endsWith("/api/scope")) return json(state.scope);
    if (url.endsWith("/api/stress-test")) return json(state.stress);
    if (url.endsWith("/api/portfolio/summary")) return json({ portfolio_id: "p", name: "n", description: "d", as_of: AS_OF, base_currency: "USD", total_value: 1, asset_count: 1, entity_count: 1, synthetic: true });
    if (url.endsWith("/api/portfolio/exposure")) return json({ by_asset_class: [], by_sector: [], by_entity: [], by_geography: [] });
    return json({ detail: "not found" }, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<FeedPage />} />
          <Route path="/analyze" element={<AnalyzePage />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="/stress" element={<StressPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("subject line", () => {
  it("names whatever the signal is about, never a blank", () => {
    expect(subjectLine({ level: "COMPANY", entityName: "Kestrel", ticker: "KSTR" })).toBe("Kestrel (KSTR)");
    expect(subjectLine({ level: "SECTOR", sector: "Energy" })).toBe("Energy sector");
    expect(subjectLine({ level: "MARKET", themes: ["growth_and_jobs", "rates"] })).toBe("Market-wide · growth and jobs, rates");
    expect(subjectLine({ level: "MARKET" })).toBe("Market-wide");
    expect(subjectLine({ level: "UNRESOLVED" })).toBe("No subject identified");
  });
});

describe("Analyze page", () => {
  it("offers one example per kind of subject and puts the text in the box", async () => {
    renderAt("/analyze");
    expect(EXAMPLES.map((e) => e.id)).toEqual(["company", "sector", "macro", "unresolved"]);
    await userEvent.click(await screen.findByRole("button", { name: "A sector" }));
    expect(screen.getByRole("textbox", { name: /Text to analyse/ })).toHaveValue(EXAMPLES[1].text);
  });

  it("posts the text and shows what it is about, the tone, the impact kind and the portfolio relevance", async () => {
    renderAt("/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), "Chipmakers slide as semiconductor demand softens");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    const result = within(await screen.findByRole("region", { name: "Analysis result" }));
    expect(result.getByText("Technology sector")).toBeInTheDocument();
    expect(result.getByText("Sector · Technology")).toBeInTheDocument();
    expect(result.getByText("New signal")).toBeInTheDocument();
    expect(result.getByText(/Sector exposure · 13\.0%/)).toBeInTheDocument();
    expect(await result.findByText(/which is 13\.0% of the book/)).toBeInTheDocument();
    expect(result.getByText(/scored by the reference model/)).toBeInTheDocument();
    expect(result.getByRole("link", { name: /Open the full analysis/ })).toHaveAttribute("href", "/events/sig_s");
    expect(result.getByRole("link", { name: "Run the scenario" })).toHaveAttribute("href", "/stress?signal=sig_s&run=1");
    const post = calls.find((c) => c.url.endsWith("/api/analyze"));
    expect(JSON.parse(post!.body!)).toMatchObject({ text: "Chipmakers slide as semiconductor demand softens", source_type: "NEWS" });
  });

  it("says why a text was rejected instead of showing a guess", async () => {
    state.analyze = analyzed({ outcome: "QUARANTINED", signal_id: null, signal: null, rejection: { code: "TOO_SHORT", detail: "2 chars < 15" }, notes: [] });
    renderAt("/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), "ok");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByText("This text could not be analysed")).toBeInTheDocument();
    expect(screen.getByText(/2 chars < 15/)).toBeInTheDocument();
    expect(screen.getByText(/instead of guessing a value/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open the full analysis/ })).not.toBeInTheDocument();
  });

  it("shows an unscored event honestly: no impact number, and the reason", async () => {
    state.analyze = analyzed({ signal: { ...sectorRow, impact_score: null, event_status: "NO_EVENT", scope_level: "UNRESOLVED", scope_sector: null, relevance_level: "UNDETERMINED", relevance_share: null } });
    renderAt("/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), "Weather is nice today");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByText(/Not a market event, so no impact is scored/)).toBeInTheDocument();
    expect(screen.getByText("Relevance unknown")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Run the scenario|Run as a what-if/ })).not.toBeInTheDocument();
  });

  it("explains an unavailable engine and disables the form", async () => {
    state.meta = { ...meta, profile: "demo", replay: null, capabilities: { analyze: false, live_enabled: false } };
    renderAt("/analyze");
    expect(await screen.findByText("Analysis is not available in this profile")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Text to analyse/ })).toBeDisabled();
  });

  it("reports an API failure in words", async () => {
    state.analyze = new Error("analysis needs the replay profile");
    renderAt("/analyze");
    await userEvent.type(await screen.findByRole("textbox", { name: /Text to analyse/ }), "Federal Reserve signals rate cuts");
    await userEvent.click(screen.getByRole("button", { name: /Analyze/ }));
    expect(await screen.findByText("The request failed")).toBeInTheDocument();
    expect(screen.getByText("analysis needs the replay profile")).toBeInTheDocument();
  });
});

describe("Risk Monitor", () => {
  it("shows the live source, its model and its market-data limit, and labels every row by what it is about and how it arrived", async () => {
    renderAt("/");
    const bar = within(await screen.findByRole("region", { name: "Live feed status" }));
    expect(bar.getByText("Live")).toBeInTheDocument();
    expect(bar.getByText(/2 live signals/)).toBeInTheDocument();
    expect(bar.getByText(/tfidf-lr-event-v1/)).toBeInTheDocument();
    expect(bar.getByText(/Reports after 2026-10-01 get the labelled placeholder impact rule/)).toBeInTheDocument();
    expect(await screen.findByText("Technology sector")).toBeInTheDocument();
    expect(screen.getByText(/Market-wide · rates/)).toBeInTheDocument();
    expect(screen.getByText("Pasted")).toBeInTheDocument();
    expect(screen.getAllByText("Live").length).toBeGreaterThan(1);
    expect(screen.getByText(/Whole book/)).toBeInTheDocument();
    expect(screen.getByText(/Sector exposure · 13\.0%/)).toBeInTheDocument();
  });

  it("says when the source is down, that nothing was invented, and offers a poll", async () => {
    state.live = liveStatus({ state: "ERROR", last_error: "api.gdeltproject.org: timeout", consecutive_failures: 4, last_success_at: null });
    renderAt("/");
    expect(await screen.findByText("Live source unreachable")).toBeInTheDocument();
    expect(screen.getByText(/Nothing was invented; the signals already here are unchanged/)).toBeInTheDocument();
    expect(screen.getByText(/4 failed polls in a row, backing off/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Poll now/ })).toBeInTheDocument();
  });

  it("is quiet and honest when live is off: replay data only, and how to turn it on", async () => {
    state.live = liveStatus({ enabled: false, state: "OFF" });
    state.meta = { ...meta, capabilities: { analyze: true, live_enabled: false } };
    renderAt("/");
    expect(await screen.findByText("Live feed off")).toBeInTheDocument();
    expect(screen.getByText(/make run-live/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Poll now/ })).not.toBeInTheDocument();
  });

  it("labels a capture as simulated", async () => {
    state.live = liveStatus({ source_mode: "CAPTURE", simulated: true });
    renderAt("/");
    expect(await screen.findByText(/simulated: a captured file replayed as if live/)).toBeInTheDocument();
  });

  it("filters by what the signal is about and by how it arrived through the API", async () => {
    renderAt("/?scope=SECTOR&channel=MANUAL");
    await screen.findByText("Technology sector");
    const feedCall = calls.find((c) => c.url.includes("/api/signals?") && c.url.includes("scope_level=SECTOR"));
    expect(feedCall?.url).toContain("channel=MANUAL");
  });

  it("counts arrivals since the page loaded and marks them", async () => {
    renderAt("/");
    await screen.findByText("Technology sector");
    expect(screen.queryByRole("button", { name: /new signal/ })).not.toBeInTheDocument(); // everything present at load is not "new"
  });
});

describe("Event page by scope", () => {
  it("a sector event names the sector, says no company was named, and shows the exposure path", async () => {
    state.detail = detail(scopeOf({ level: "SECTOR", sector: "Technology", strength: "STRONG", basis: "SECTOR_TERMS", matched_terms: { sector: ["chipmakers", "semiconductor"] }, note: "No company was named; 2 Technology terms point to that sector." }), noEntity);
    renderAt("/events/sig_x");
    expect((await screen.findAllByText("Technology sector")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2 Technology terms point to that sector/).length).toBeGreaterThan(0);
    expect(screen.getByText("chipmakers, semiconductor")).toBeInTheDocument();
    expect(await screen.findByText("Sector exposure")).toBeInTheDocument();
    expect(screen.getByText(/1 of 4 of its shocks reach this kind of event/)).toBeInTheDocument();
    expect(screen.getByText("Sector and market-wide shocks apply")).toBeInTheDocument();
    expect(screen.queryByText(/Company not identified/)).not.toBeInTheDocument();
  });

  it("a market-wide event is not reported as a failure to find a company", async () => {
    state.detail = detail(scopeOf({ level: "MARKET", sector: null, themes: ["rates"], basis: "THEME_TERMS", note: "No company or sector was named; market-wide vocabulary (fed)." }), noEntity);
    state.relevance = relevance({ scope_level: "MARKET", level: "MARKET_WIDE", share: 1, summary: "A market-wide event (rates): it reaches the whole book." });
    renderAt("/events/sig_x");
    expect((await screen.findAllByText("Market-wide · rates")).length).toBeGreaterThan(0);
    expect(screen.queryByText(/Company-specific portfolio stress is therefore unavailable/)).not.toBeInTheDocument();
    expect(screen.queryByText("No subject identified")).not.toBeInTheDocument();
    expect(await screen.findByText("Only market-wide shocks apply")).toBeInTheDocument();
  });

  it("novelty is not presented as a measurement when there was no issuer to compare with", async () => {
    state.detail = detail(scopeOf({ level: "MARKET", sector: null }), noEntity);
    renderAt("/events/sig_x");
    expect(await screen.findByText("not measured: no issuer to compare with")).toBeInTheDocument();
  });
});

describe("Portfolio Stress: an event the scenario cannot reach", () => {
  it("says so instead of reporting a zero", async () => {
    state.detail = detail(scopeOf({ level: "UNRESOLVED", sector: null }), noEntity);
    state.stress = {
      run_id: "r", status: "NOT_APPLICABLE", reason: "No shock in 'M&A repricing' reaches what this event is about (no company, sector or market theme could be identified).",
      signal_id: "sig_x", scenario: null, severity: null, shocks: [], summary: null, positions: [], contributions: null, uncovered: null,
      audit: { mode: "REPLAY", data_origin: "REAL_SOURCE_MIXED_NLP", engine_version: "1", scenario_version: "1", portfolio_id: "p", portfolio_hash: "h", threshold: 7, forced: true, impact_overridden: false, scope_level: "UNRESOLVED", scope_note: "n", calculated_at: AS_OF, calculation: "d" },
    };
    renderAt("/stress?signal=sig_x&run=1");
    expect(await screen.findByText("This scenario does not reach what the event is about")).toBeInTheDocument();
    expect(screen.getByText(/rather than reporting a zero|reaches what this event is about/)).toBeInTheDocument();
  });
});

describe("Evidence: Scope tab", () => {
  it("shows the rules, the data mix and the measured vocabulary with its limits", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ScopeTab />
      </QueryClientProvider>,
    );
    expect(await screen.findByText("How the subject of a signal is decided")).toBeInTheDocument();
    expect(screen.getByText("A resolved company is the scope (COMPANY).")).toBeInTheDocument();
    expect(screen.getByText("Strong (two or more terms)").closest("tr")).toHaveTextContent("90%");
    expect(screen.getByText("Weak (one term)").closest("tr")).toHaveTextContent("81%");
    expect(screen.getByText(/an optimistic proxy for the no-company case/)).toBeInTheDocument();
    expect(screen.getByText(/There is no industry level/)).toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Scenario, SignalSummary, StressResult } from "../../api/types";
import { CommandPalette } from "../CommandPalette";
import { EventStream } from "../desk/EventStream";
import { ScenarioRail } from "../portfolio/ScenarioRail";
import { ValueBridge } from "../portfolio/ValueBridge";
import { SignalTrace } from "./SignalTrace";

const caps = { assessment: true, intelligence: true, propagation: true, analyze: true, monitor: false, live_enabled: false };
const meta = {
  app: "EventShock", profile: "replay", replay: { snapshot_id: "x" }, as_of: "2026-10-01T12:00:00Z", trigger_threshold: 7, capabilities: caps,
  taxonomy: [{ id: "GEOPOLITICAL", label: "Geopolitical", description: "", default_scenario: "scn_geo" }],
};
const signal = {
  id: "sig_h", status: "COMPLETE",
  document: { source: "aol.com", source_type: "NEWS", published_at: "2026-09-20T15:30:00Z", headline: "Strait closed again", body: null },
  entity: { entity_id: "UNKNOWN_ENTITY", entity_name: null, ticker: null, sector: null, link_confidence: 0 },
  scope: { level: "MARKET", sector: null, regions: [], themes: [], basis: "THEME_TERMS", strength: "STRONG", note: "" },
  sentiment: { positive: 0.1, neutral: 0.8, negative: 0.1, score: 0.02 },
  event: { category: "GEOPOLITICAL", status: "CLASSIFIED", probabilities: { GEOPOLITICAL: 0.71 }, no_event_probability: null },
  impact: null,
  evidence: { source_count: 1, unique_domain_count: 1, novelty_score: 0.5, novelty_measured: false, model_confidence: 0.71, corroborating: [], contradicted_by: [] },
  provenance: null, data_origin: "REAL_SOURCE_MIXED_NLP", model_versions: {},
};
const assessment = {
  extraction: { mode: "RULES" }, severity_note: null,
  reading: { event_type: "GEOPOLITICAL", event_label: "Geopolitical", event_confidence: 0.71, sentiment: 0.02, evidence: [{ quote: "closed", start: 0, end: 6, supports: "x" }] },
  severity: { score: 8, low: 6, high: 8, band_label: "High", version: "severity-v2", reliability: { level: "moderate" } },
};
const preview = { availability: "AVAILABLE", status: "COMPLETED", scenario_id: "scn_geo", scenario_name: "Flight to safety", baseline_value: 860_100_000, stressed_value: 822_800_000, pnl: -37_300_000, pnl_pct: -0.0433, reason: null, note: "", run_id: "r1", severity_score: 8, trigger_threshold: 7 };
const intel = (stress: object) => ({
  evidence: { availability: "AVAILABLE", independent_sources: 1, unique_domains: 1, syndicated_copies: 0, evidence_strength: { tier: "INSUFFICIENT", rule: "r", reasons: [], components: {} } },
  lifecycle: { availability: "AVAILABLE", state: "DEVELOPING" }, novelty: { availability: "AVAILABLE", label: "NEW" },
  stress,
});
const scenario = { id: "scn_geo", name: "Flight to safety", category: "GEOPOLITICAL", description: "", illustrative: true, reference_impact: 7, version: "1", shocks: [{ factor: "EQUITY", scope: "MARKET", value: -0.08, rationale: "risk-off", sector: null, currency: null, entity_id: null }] };
const flow = (gen: object) => ({
  graph: { availability: "AVAILABLE", reached_share: 0.845, nodes: [{ id: "target:ASSET_CLASS:EQUITY", kind: "ASSET_CLASS", label: "Equity positions", share: 0.352, value: 1, detail: null }] },
  materiality: { availability: "AVAILABLE", level: "CRITICAL" },
  scenario: gen,
});

let intelResponse: object = intel(preview);
let flowResponse: object = flow({ availability: "AVAILABLE", gates: [], scenario });

function stub() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/meta")) return json(meta);
      if (url.includes("/assessment")) return json(assessment);
      if (url.includes("/intelligence")) return json(intelResponse);
      if (url.includes("/propagation")) return json(flowResponse);
      if (url.endsWith("/api/scenarios")) return json({ version: "1", default_by_category: { GEOPOLITICAL: "scn_geo" }, scenarios: [scenario] });
      if (url.includes("/api/signals?") || url.endsWith("/api/signals")) return json({ total: 0, seq: 0, items: [] });
      if (url.includes("/api/signals/")) return json(signal);
      return json({ detail: "not found" }, 404);
    }),
  );
}

const wrap = (ui: React.ReactNode, path = "/") =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => {
  intelResponse = intel(preview);
  flowResponse = flow({ availability: "AVAILABLE", gates: [], scenario });
  stub();
});
afterEach(() => vi.unstubAllGlobals());

describe("SignalTrace", () => {
  it("draws six stations from the source to the portfolio, each from a real endpoint", async () => {
    wrap(<SignalTrace signalId="sig_h" />);
    const trace = await screen.findByRole("region", { name: "Signal trace" });
    expect(await within(trace).findByText("−$37.3M")).toBeInTheDocument();
    const stations = within(trace).getAllByRole("listitem").filter((li) => li.classList.contains("station"));
    expect(stations).toHaveLength(6);
    expect(within(trace).getByText("aol.com")).toBeInTheDocument();
    expect(within(trace).getByText("71% confident")).toBeInTheDocument();
    expect(within(trace).getByText("8")).toBeInTheDocument();
    expect(within(trace).getByText("Flight to safety")).toBeInTheDocument();
    expect(within(trace).getByText("Critical materiality")).toBeInTheDocument();
    expect(within(trace).getByText("−4.33% of the book")).toBeInTheDocument();
    expect(within(trace).getByText(/Scenario simulation, not a prediction/)).toBeInTheDocument();
    expect(within(trace).getByRole("link", { name: "Open in Stress Lab" })).toHaveAttribute("href", "/stress?signal=sig_h&run=1");
  });

  it("says when the scenario is unavailable and which gate failed, and shows no portfolio number below the trigger", async () => {
    flowResponse = flow({ availability: "UNAVAILABLE", gates: [{ id: "sev", label: "Severity", passed: false, detail: "severity 2 is below 7" }], scenario: null });
    intelResponse = intel({ ...preview, availability: "UNAVAILABLE", status: "NOT_TRIGGERED", pnl: null, baseline_value: null, stressed_value: null, pnl_pct: null, reason: "Severity 2 is below the trigger 7." });
    wrap(<SignalTrace signalId="sig_h" />);
    const trace = await screen.findByRole("region", { name: "Signal trace" });
    expect(await within(trace).findByText("Scenario unavailable")).toBeInTheDocument();
    expect(within(trace).getByText(/Severity: severity 2 is below 7/)).toBeInTheDocument();
    expect(await within(trace).findByText("Below the trigger")).toBeInTheDocument();
    expect(within(trace).queryByText(/\$/)).toBeNull();
  });
});

const row = (id: string, at: string, over: Partial<SignalSummary> = {}) =>
  ({ id, headline: `Headline ${id}`, published_at: at, category: "GEOPOLITICAL", event_status: "CLASSIFIED", source_count: 1, severity_score: 6, impact_score: 6, ticker: null, entity_name: null, ...over }) as unknown as SignalSummary;

describe("EventStream", () => {
  it("lists events newest first, selects on click and moves with J / K", async () => {
    const onSelect = vi.fn();
    const items = [row("a", "2026-09-20T10:00:00Z"), row("b", "2026-09-21T10:00:00Z"), row("n", "2026-09-22T10:00:00Z", { event_status: "NO_EVENT" })];
    wrap(<EventStream items={items} selected="b" onSelect={onSelect} label={(c) => c} assessed total={3} />);
    const list = screen.getByRole("list", { name: "Market events, newest first" });
    const buttons = within(list).getAllByRole("button");
    expect(buttons.map((b) => b.getAttribute("data-id"))).toEqual(["b", "a"]); // the non-event is not on the wire
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(buttons[1]!);
    expect(onSelect).toHaveBeenLastCalledWith("a");
    fireEvent.keyDown(window, { key: "j" });
    expect(onSelect).toHaveBeenLastCalledWith("a");
  });

  it("filters the wire by event type", async () => {
    const items = [row("a", "2026-09-20T10:00:00Z"), row("m", "2026-09-21T10:00:00Z", { category: "MACROECONOMIC" })];
    wrap(<EventStream items={items} selected="a" onSelect={() => {}} label={(c) => (c === "MACROECONOMIC" ? "Macroeconomic" : "Geopolitical")} assessed total={2} />);
    await userEvent.click(screen.getByRole("button", { name: /Macroeconomic/ }));
    const list = screen.getByRole("list", { name: "Market events, newest first" });
    // a type filter narrows the wire to that type only
    expect(within(list).getAllByRole("button").map((b) => b.getAttribute("data-id"))).toEqual(["m"]);
  });
});

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

describe("CommandPalette", () => {
  it("opens with ⌘K, filters pages, and navigates", async () => {
    wrap(
      <Routes>
        <Route path="*" element={<><CommandPalette /><Where /></>} />
      </Routes>,
    );
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    const dialog = await screen.findByRole("dialog", { name: "Jump to anything" });
    await userEvent.type(within(dialog).getByRole("combobox"), "stress lab");
    expect(within(dialog).getByRole("option", { name: /Stress Lab/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByTestId("where").textContent).toBe("/stress");
  });

  it("offers the current page's explanations and opens them by URL", async () => {
    wrap(
      <Routes>
        <Route path="*" element={<><CommandPalette /><Where /></>} />
      </Routes>,
      "/stress?signal=s1",
    );
    fireEvent.keyDown(window, { key: "/" });
    const dialog = await screen.findByRole("dialog", { name: "Jump to anything" });
    await userEvent.click(within(dialog).getByRole("option", { name: /How the scenario is calculated/ }));
    expect(screen.getByTestId("where").textContent).toContain("open=math");
  });
});

const result = (deltas: [string, number, number][], pnl: number) =>
  ({
    run_id: "r", status: "COMPLETED", positions: [], shocks: [{ factor: "EQUITY", scope: "MARKET", base_value: -0.1, scaled_value: -0.1, applicable: true, rationale: "", sector: null, currency: null }],
    severity: { scale: 1 },
    summary: { baseline_value: 1_000_000, stressed_value: 1_000_000 + pnl, pnl, pnl_pct: pnl / 1_000_000 },
    contributions: { by_asset_class: deltas.map(([key, baseline_value, delta]) => ({ key, label: key, baseline_value, delta, share_of_loss: 0 })), top_positions: [], by_sector: [], by_entity: [], by_factor: [] },
  }) as unknown as StressResult;

describe("ValueBridge", () => {
  it("traces the change by asset class and reconciles to the total", () => {
    wrap(<ValueBridge r={result([["EQUITY", 600_000, -60_000], ["BOND", 400_000, -10_000]], -70_000)} />);
    expect(screen.getAllByText("Equities").length).toBeGreaterThan(0);
    expect(screen.getByText("−$60.0K")).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("refuses to pretend a breakdown reconciles when it does not", () => {
    wrap(<ValueBridge r={result([["EQUITY", 600_000, -60_000]], -70_000)} />);
    expect(screen.getByRole("status")).toHaveTextContent(/does not reconcile/);
  });
});

describe("ScenarioRail", () => {
  const scenarios = [
    { ...scenario, id: "scn_a", name: "Alpha" },
    { ...scenario, id: "scn_b", name: "Oil", shocks: [{ factor: "COMMODITY_PCT", scope: "MARKET", value: 0.35, rationale: "", sector: null, currency: null, entity_id: null }] },
  ] as unknown as Scenario[];
  it("marks the mapped scenario, labels multi-factor ones, and runs a pick", async () => {
    const onPick = vi.fn();
    wrap(<ScenarioRail scenarios={scenarios} selected="scn_a" mapped="scn_a" onPick={onPick} />);
    expect(screen.getByText("matches this event")).toBeInTheDocument();
    expect(screen.getByText("multi-factor")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Oil/ }));
    expect(onPick).toHaveBeenCalledWith("scn_b");
  });
});

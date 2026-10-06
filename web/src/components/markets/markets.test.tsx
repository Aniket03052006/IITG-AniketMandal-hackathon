import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExternalMarketCard, ExternalMarketView, FourWayLegend } from "./ExternalMarketCard";

const prov = [{ kind: "EXTERNAL_MARKET_OBSERVATION", source: "fixture", ref_id: "m", as_of: "2026-09-25T12:00:00Z" }];
const base = {
  version: "external-markets-v1", event_id: "evt_1", signal_id: "s1", as_of: "2026-09-25T22:00:00Z", availability: "AVAILABLE", reason: null, label: "EXTERNAL MARKET OBSERVATION",
  note: "EXTERNAL MARKET OBSERVATION: never an input to any EventShock number.", caveats: ["A market price is not ground truth."], provenance: prov,
  provider: { provider: "kalshi", category: "PREDICTION_MARKET", state: "AVAILABLE", mode: "fixture", reason: "SYNTHETIC FIXTURE: not market data", observed_from: null, observed_through: null, synthetic: true },
  eventshock_severity: 8, eventshock_materiality: "HIGH", interpretation: null,
};
const matched = {
  ...base,
  match: {
    status: "MATCHED", reason: "matched", theme_id: "FED_POLICY", theme_label: "US monetary policy", evidence: ["scope theme"], event_gates: [{ id: "SUBJECT", label: "Subject", passed: true, detail: "scope theme" }],
    candidates: [{ market_id: "M1", question: "Will the Fed cut?", chosen: true, gates: [{ id: "OPEN", label: "Open", passed: true, detail: "active" }] }],
    market: { provider: "kalshi", category: "PREDICTION_MARKET", source: "fixture", market_id: "M1", series_id: "S", question: "Will the Fed cut?", probability: 0.72, previous_probability: 0.48, probability_change_pp: 24, observed_at: "2026-09-25T12:00:00Z", previous_observed_at: null, market_status: "OPEN", raw_status: "active", volume: 100, volume_24h: null, open_interest: 5000, close_time: null, source_url: null, synthetic: true, provenance: prov },
  },
  interpretation: { code: "MARKET_REPRICED", text: "External market observation moved by 24.0 pp.", reason: "r", rule: "R1", eventshock_elevated: true, eventshock_direction: null, market_direction: "TOWARD_RISK", orientation: "NEUTRAL", caveats: [] },
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("ExternalMarketView", () => {
  it("shows the probability, the change in pp, the interpretation and the never-an-input note", () => {
    wrap(<ExternalMarketView v={matched as never} />);
    expect(screen.getAllByText("Will the Fed cut?").length).toBeGreaterThan(0);
    expect(screen.getByText("72%")).toBeTruthy();
    expect(screen.getByText("+24.0 pp")).toBeTruthy();
    expect(screen.getByText("Market repriced")).toBeTruthy();
    expect(screen.getByText(/never an input/)).toBeTruthy();
    expect(screen.queryByText(/confirms/i)).toBeNull();
  });

  it("says what is true when nothing is matched, with the fixed sentence", () => {
    const v = { ...base, match: { status: "NO_MATCH", reason: "no curated theme applies", theme_id: null, theme_label: null, evidence: [], event_gates: [], candidates: [], market: null } };
    wrap(<ExternalMarketView v={v as never} />);
    expect(screen.getByText("No relevant external prediction market identified.")).toBeTruthy();
  });

  it("says unavailable when the provider is down", () => {
    const v = { ...base, availability: "UNAVAILABLE", reason: "External market data unavailable.", match: null };
    wrap(<ExternalMarketView v={v as never} />);
    expect(screen.getByText("External market data unavailable.")).toBeTruthy();
  });
});

describe("ExternalMarketCard", () => {
  it("renders nothing when the capability is off", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ capabilities: { external_markets: false } }), { status: 200 })));
    const { container } = wrap(<ExternalMarketCard eventId="evt_1" />);
    await waitFor(() => expect(container.querySelector("section")).toBeNull());
  });

  it("labels the section and the observation when served", async () => {
    vi.stubGlobal("fetch", vi.fn(async (u: string) => new Response(JSON.stringify(String(u).includes("/meta") ? { capabilities: { external_markets: true, explanations: false } } : matched), { status: 200 })));
    wrap(<ExternalMarketCard eventId="evt_1" />);
    await waitFor(() => expect(screen.getByText("72%")).toBeTruthy());
    expect(screen.getAllByText(/EXTERNAL MARKET OBSERVATION/).length).toBeGreaterThan(0);
    expect(screen.getByText(/SYNTHETIC FIXTURE/)).toBeTruthy();
  });
});

describe("FourWayLegend", () => {
  it("names the four kinds", () => {
    render(<FourWayLegend />);
    for (const k of ["MODEL ASSESSMENT", "HISTORICAL OBSERVATION", "EXTERNAL MARKET OBSERVATION", "SCENARIO ASSUMPTION"]) expect(screen.getByText(k)).toBeTruthy();
  });
});

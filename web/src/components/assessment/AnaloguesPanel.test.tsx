import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Analogue, AnalogueSet } from "../../api/types";
import { AnaloguesPanel, AnaloguesView } from "./AnaloguesPanel";

const item = (over: Partial<Analogue> = {}): Analogue => ({
  id: "d1", origin: "RETRIEVED", headline: "Acme recalls 200,000 vehicles over braking fault", published_at: "2024-03-04T21:30:00+00:00", reaction_session: "2024-03-05",
  scope: "ISSUER", ticker: "ACME", sector: "Consumer", similarity: 0.91, car_pct: -2.4, z: -1.8, abs_z: 1.8, vix_level: 14.2, outcome_version: "outcome-v3",
  model_event_type: "PRODUCT_OPERATIONS", ...over,
});

const base: AnalogueSet = {
  status: "OK", reason: "5 of 7 distinct past stories shown (similarity at least 0.84).", scope: "ISSUER", query_date: "2026-09-30", similarity_floor: 0.84, eligible: 4100, above_floor: 9,
  items: [item(), item({ id: "d2", headline: "Beta Corp halts production at its main plant", ticker: "BETA", car_pct: 0.4, z: 0.3, abs_z: 0.3, similarity: 0.88, vix_level: 21.5 })],
  aggregate: {
    n_episodes: 9, n_stories: 7, n_used: 7, car_pct_q10: -2.4, car_pct_q50: -0.3, car_pct_q90: 0.8, abs_car_pct_median: 0.9, share_move_ge_2sigma: 0.14, share_lo: 0.04, share_hi: 0.4,
    quiet_day_share: 0.051, lift: 2.7, distinguishable_from_quiet_day: false,
    reading: "The market's reaction after these past reports is not distinguishable from an ordinary day: similar headlines were usually followed by an ordinary move.",
  },
  below_bar: [], caveats: ["Past outcomes are hindsight about other reports, not a forecast for this one."], index_version: "analogue-index-v1+e5",
  outcome_note: "The realised move is hindsight about a PAST report. It is not a forecast for this report.",
};

describe("AnaloguesView", () => {
  it("shows precedent with the move, similarity and regime, and says when it is not distinguishable from an ordinary day", () => {
    render(<AnaloguesView set={base} />);
    expect(screen.getByText(/not distinguishable from an ordinary day/i)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /resemble this one/i });
    expect(within(table).getByText(/Acme recalls 200,000 vehicles/)).toBeInTheDocument();
    expect(within(table).getByText("0.91")).toBeInTheDocument();
    expect(within(table).getByText(/−2\.40%/)).toBeInTheDocument();          // a signed, minus-sign move, not colour alone
    expect(within(table).getByText(/−1\.8σ/)).toBeInTheDocument();
    expect(within(table).getByText("14.2")).toBeInTheDocument();
    expect(screen.getAllByText(/hindsight/i).length).toBeGreaterThan(0);
  });

  it("states the group figures against the ordinary-day yardstick", () => {
    render(<AnaloguesView set={base} />);
    const g = screen.getByLabelText(/what the analogues say as a group/i);
    expect(within(g).getByText(/Statistics are based on/)).toBeInTheDocument();
    expect(within(g).getByText(/most similar of 7 distinct past stories/)).toBeInTheDocument();
    expect(within(g).getByText(/The same on an ordinary day/)).toBeInTheDocument();
    expect(within(g).getByText(/5\.1%/)).toBeInTheDocument();
  });

  it("says plainly that no reliable analogue was found, pads nothing, and keeps the nearest matches out of the precedent table", () => {
    const none: AnalogueSet = { ...base, status: "NO_RELIABLE_ANALOGUE", reason: "Only 2 distinct past episode(s) (1 distinct story) resemble this report closely enough.", items: [], aggregate: null,
      below_bar: [item({ similarity: 0.79 })] };
    render(<AnaloguesView set={none} />);
    expect(screen.getByText("No reliable historical analogue found")).toBeInTheDocument();
    expect(screen.getByText(/Only 2 distinct past episode/)).toBeInTheDocument();
    expect(screen.getByText(/does not invent a precedent/i)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: /resemble this one/i })).toBeNull();
    expect(screen.getByText(/below the reliability bar \(not precedent\)/i)).toBeInTheDocument();
    expect(screen.queryByText(/lift/)).toBeNull();
  });

  it("explains an unavailable index or encoder instead of showing an empty answer", () => {
    render(<AnaloguesView set={{ ...base, status: "UNAVAILABLE", reason: "Analogue search needs the sentence encoder for text it has not seen.", items: [], aggregate: null }} />);
    expect(screen.getByText("Analogue search is not available for this report")).toBeInTheDocument();
    expect(screen.getByText(/needs the sentence encoder/)).toBeInTheDocument();
    expect(screen.queryByText("No reliable historical analogue found")).toBeNull();
  });

  it("does not claim a lift when the group is distinguishable only if the server says so", () => {
    const strong: AnalogueSet = { ...base, aggregate: { ...base.aggregate!, distinguishable_from_quiet_day: true, reading: "The market's reaction after these past reports was larger than on an ordinary day." } };
    render(<AnaloguesView set={strong} />);
    expect(screen.getByText(/larger than on an ordinary day/)).toBeInTheDocument();
  });
});

describe("AnaloguesPanel", () => {
  afterEach(() => vi.unstubAllGlobals());
  const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);

  it("renders nothing and makes no request when analogues are not enabled", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = wrap(<AnaloguesPanel signalId="sig_1" enabled={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("labels the section as retrieved precedent and loads it from the API", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      expect(url).toContain("/signals/sig_1/analogues");
      return new Response(JSON.stringify(base), { status: 200, headers: { "content-type": "application/json" } });
    }));
    wrap(<AnaloguesPanel signalId="sig_1" enabled />);
    expect(screen.getByRole("heading", { name: "Historical analogues" })).toBeInTheDocument();
    expect(screen.getAllByText("Retrieved").length).toBeGreaterThan(0);
    expect(screen.getByText(/never changes the severity score/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Acme recalls 200,000 vehicles/)).toBeInTheDocument());
  });

  it("reports a failed request as a warning rather than an empty section", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500, headers: { "content-type": "application/json" } })));
    wrap(<AnaloguesPanel signalId="sig_1" enabled />);
    await waitFor(() => expect(screen.getByText("Analogues could not be loaded")).toBeInTheDocument());
  });
});

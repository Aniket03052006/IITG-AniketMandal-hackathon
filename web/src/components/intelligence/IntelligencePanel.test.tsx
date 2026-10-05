import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EventIntelligence } from "../../api/types";
import { IntelligencePanel, IntelligenceSummary, IntelligenceView } from "./IntelligencePanel";

const T0 = "2026-09-01T09:00:00Z";
const T1 = "2026-09-01T10:00:00Z";

const claim = (id: string, source: string, polarity: string, quote: string, at: string, attributed = false) => ({
  id, report_id: id, signal_id: "s", source, published_at: at, axis: "confirmation", predicate: "confirmation", verb: polarity, polarity, subject: "Acme", object: "the sale",
  attributed, evidence_span: { quote, start: 0, end: quote.length }, full_text: true,
});

const intel = (over: Partial<EventIntelligence> = {}): EventIntelligence =>
  ({
    signal_id: "sig_a", version: "intelligence-v1", as_of: T1, as_of_basis: "LAST_REPORT",
    event: { headline: "Acme confirms sale", event_type: "MA_CORPORATE_ACTION", event_label: "M&A / Corporate Action", event_subtype_label: "Acquisition", event_status: "CLASSIFIED", sentiment: -0.2, sentiment_label: "negative", severity_score: 5, severity_band: "moderate", impact_score: 6, impact_origin: "MODEL", extraction_mode: "RULES" },
    group: {
      event_id: "evt_1", anchor_signal_id: "sig_a", signal_ids: ["sig_a"], headline: "Acme confirms sale", report_count: 2, independent_sources: 2, first_seen: T0, last_seen: T1, grouping_note: "One report cluster.",
      reports: [
        { id: "d1", signal_id: "sig_a", source: "Wire A", source_type: "NEWS", domain: "a.example", url: "https://a.example/1", published_at: T0, headline: "Acme confirms sale", relation: "CANONICAL", independent: true, clock_trusted: true, phase: "AT_REPORT" },
        { id: "d2", signal_id: "sig_a", source: "Wire B", source_type: "NEWS", domain: "b.example", url: null, published_at: T1, headline: "Acme denies sale", relation: "SAME_EVENT", independent: true, clock_trusted: true, phase: "AFTER_REPORT" },
      ],
    },
    provenance: { channel: "MANUAL", adapter: "manual-paste", timestamp_origin: "ANALYSIS_TIME", clock_trusted: true, content_sha256: "0".repeat(64), snapshot_id: null },
    scope: {
      scope_type: "COMPANY", scope_value: "Acme Corp", resolver_version: "v", resolution_status: "RESOLVED", candidates: [], secondary: [], reason: "Acme Corp was named in the text.",
      scope_path: [
        { type: "COMPANY", value: "Acme Corp", basis: "ENTITY_RESOLVER" }, { type: "SECTOR", value: "Industrials", basis: "ENTITY_MASTER" }, { type: "MARKET", value: "Equity market", basis: "HIERARCHY_ROOT" },
      ],
      scope_confidence: { tier: "HIGH", basis: "the entity resolver matched Acme", measured: null }, scope_evidence: [{ dimension: "company", term: "Acme", quote: "Acme", start: 0, end: 4 }],
    },
    evidence: {
      availability: "AVAILABLE", reason: null, source_count: 2, independent_sources: 2, unique_domains: 2, source_diversity: 1, syndicated_copies: 0, authoritative_sources: 0, authoritative_supported: false,
      authoritative_domains: [], first_observed: T0, latest_observed: T1, entity_confidence: 0.95, entity_basis: "rule ALIAS", scope_confidence: "HIGH",
      model_confidence: [
        { stage: "event", value: 0.61, basis: "calibrated P of the top class", status: "classified: the model committed to a class" },
        { stage: "sentiment", value: 0.7, basis: "largest class probability", status: "trained model (experimental)" },
        { stage: "impact", value: null, basis: "a 1-10 proxy, not a probability", status: "trained impact model (experimental)" },
      ],
      source_disagreement: "NONE", note: "Evidence strength says how well the event is corroborated. Model confidence says how sure a model is of its own output.",
      evidence_strength: { tier: "MODERATE", rule: "MODERATE_INDEPENDENT", reasons: ["2 independent sources (≥2)"], components: { reports: 2 } },
    },
    novelty: { availability: "AVAILABLE", reason: null, label: "NEW", rule: "NO_PRIOR", novelty_score: 1, novelty_measured: true, nearest_prior: [], narrative_match: null, new_information: [], continuation_indicators: ["no earlier event of this subject"], recurrence_cues: [] },
    velocity: { availability: "AVAILABLE", reason: null, series: [{ at: T0, independent_sources: 1, reports: 1 }, { at: T1, independent_sources: 2, reports: 2 }], window_start: T0, window_end: T1, window_hours: 1, source_growth: "1 → 2 independent sources over 1.0 h", velocity_per_hour: 1, acceleration: null, acceleration_reason: "2 reports: acceleration needs at least 5.", note: "Velocity is evidence." },
    contradiction: { availability: "AVAILABLE", reason: null, state: "NO_CONFLICT", claims_extracted: 0, conflicts: [], sequential_changes: [], tone_divergence: null, method: "Closed-lexicon claim extraction." },
    lifecycle: {
      availability: "AVAILABLE", reason: null, state: "CONFIRMED", since: T1, first_seen: T0, last_updated: T1, as_of: T1, as_of_basis: "LAST_REPORT", note: "State follows explicit evidence.",
      transitions: [
        { at: T0, from_state: null, to_state: "DEVELOPING", rule: "FIRST_REPORT", rule_text: "The first report of the event.", evidence_report_ids: ["d1"], evidence_quote: "Acme confirms sale" },
        { at: T1, from_state: "DEVELOPING", to_state: "CONFIRMED", rule: "CONFIRMED_INDEPENDENT", rule_text: "Enough independent sources now carry the event.", evidence_report_ids: ["d2"], evidence_quote: null },
      ],
    },
    affected: { entities: [{ name: "Acme Corp", kind: "COMPANY", role: "subject", resolved: true, entity_id: "E", ticker: "ACME", origin: "RULES" }], sectors: [{ sector: "Industrials", origin: "DATA", basis: "scope path (entity_master)" }], regions: ["United States"], risk_factors: [{ factor: "EQUITY", origin: "SCENARIO", basis: "the default scenario applies a market shock to it: an assumption" }], note: "Risk factors are an assumption." },
    relevance: null,
    stress: { availability: "ABSTAINED", status: "NOT_TRIGGERED", reason: "Severity 5 is below the trigger threshold 7.", scenario_id: null, scenario_name: null, severity_score: 5, trigger_threshold: 7, baseline_value: null, stressed_value: null, pnl: null, pnl_pct: null, run_id: null, note: "A modeled outcome." },
    abstentions: [],
    labels: ["Scope: deterministic vocabulary rules (RULES)."], limitations: ["Claim extraction reads a closed list of cue phrases."],
    ...over,
  }) as EventIntelligence;

const wrap = (ui: React.ReactElement, path = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
};

afterEach(() => vi.unstubAllGlobals());

describe("IntelligenceView", () => {
  it("shows the scope hierarchy from the company up to the market", () => {
    wrap(<IntelligenceView i={intel()} />);
    const path = screen.getByRole("list", { name: /scope hierarchy/i });
    expect(within(path).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      expect.stringContaining("Acme Corp"), expect.stringContaining("Industrials"), expect.stringContaining("Equity market"),
    ]);
  });

  it("keeps evidence strength and model confidence in separate tiles", () => {
    wrap(<IntelligenceView i={intel()} />);
    const strength = screen.getByRole("group", { name: "Evidence strength" });
    const conf = screen.getByRole("group", { name: "Model confidence" });
    expect(strength).toHaveTextContent(/moderate/i);
    expect(strength).toHaveTextContent(/2 independent sources among 2 reports/);
    expect(conf).toHaveTextContent(/event 61%/i);
    expect(conf).not.toHaveTextContent(/independent/i);
    expect(strength).not.toHaveTextContent(/61%/);
  });

  it("labels severity as a triage scale and the trained impact separately", () => {
    wrap(<IntelligenceView i={intel()} />);
    const impact = screen.getByRole("group", { name: "Impact" });
    expect(impact).toHaveTextContent("Severity 5/10");
    expect(impact).toHaveTextContent(/not outcome-calibrated/i);
    expect(impact).toHaveTextContent(/trained impact stage says 6\/10 \(experimental model\)/i);
  });

  it("states what it does not claim for an unresolved event, with reasons", () => {
    const i = intel({
      scope: { ...intel().scope, scope_type: "UNRESOLVED", scope_value: null, scope_path: [], resolution_status: "UNRESOLVED", scope_confidence: { tier: "NONE", basis: "no vocabulary evidence", measured: null }, scope_evidence: [], reason: "Kept as reported, not guessed about: no company, sector, region or market-wide theme could be identified." },
      abstentions: [
        { field: "company", state: "UNKNOWN", reason: "no listed company was named in the text" },
        { field: "impact", state: "UNAVAILABLE", reason: "no impact was scored for this signal" },
      ],
      lifecycle: { ...intel().lifecycle, availability: "UNAVAILABLE", state: null, reason: "The report timestamps were assigned by the replay.", transitions: [] },
    });
    wrap(<IntelligenceView i={i} />);
    expect(screen.getByText(/no hierarchy/i)).toBeInTheDocument();
    const notice = screen.getByText(/what eventshock does not claim here/i).closest("div")!;
    expect(notice).toHaveTextContent(/company: unknown\. no listed company was named/i);
    expect(notice).toHaveTextContent(/impact: unavailable/i);
    expect(screen.getByRole("group", { name: "Lifecycle" })).toHaveTextContent(/unavailable/i);
    expect(screen.getByRole("group", { name: "Lifecycle" })).toHaveTextContent(/assigned by the replay/i);
  });

  it("shows both sides of a contradiction with their source, time and verbatim clause", () => {
    const a = claim("c1", "Wire A", "confirmed", "Acme confirms the sale", T0);
    const b = claim("c2", "Wire B", "denied", "Acme denies the sale", T1);
    const i = intel({
      contradiction: {
        ...intel().contradiction, state: "CONFLICTED", claims_extracted: 2, reason: null,
        conflicts: [{ id: "cf", axis: "confirmation", axis_label: "Confirmation", state: "CONFLICTED", side_a: a, side_b: b, shared_topic: ["acme", "sale"], hours_apart: 1, reason: "Wire A reports 'confirmed' and Wire B reports 'denied' (explicit, unhedged, different outlets).", resolved_by: null, resolution: null }],
      },
      evidence: { ...intel().evidence, source_disagreement: "CONFLICTED" },
    });
    wrap(<IntelligenceView i={i} />);
    expect(screen.getByRole("group", { name: "Conflicts" })).toHaveTextContent(/conflicted/i);
    const list = screen.getByRole("list", { name: /conflicting claims/i });
    expect(within(list).getByText(/Wire A says/)).toBeInTheDocument();
    expect(within(list).getByText(/Wire B says/)).toBeInTheDocument();
    expect(within(list).getByText(/“Acme confirms the sale”/)).toBeInTheDocument();
    expect(within(list).getByText(/“Acme denies the sale”/)).toBeInTheDocument();
    expect(screen.getByText(/Conflicting reports/).closest("details")).toHaveAttribute("open");
  });

  it("does not present tone as a contradiction", () => {
    const i = intel({ contradiction: { ...intel().contradiction, tone_divergence: { signal_id: "x", headline: "Acme shares slump", sentiment: -0.8, hours_apart: 5, note: "opposite tone" } } });
    wrap(<IntelligenceView i={i} />);
    expect(screen.getByText(/context only, not a contradiction/i)).toBeInTheDocument();
  });

  it("renders the lifecycle timeline with each step's rule, and says timed transitions were not caused by a report", async () => {
    const life = intel().lifecycle;
    const i = intel({ lifecycle: { ...life, state: "STALE", transitions: [...life.transitions, { at: "2026-09-04T10:00:00Z", from_state: "CONFIRMED", to_state: "STALE", rule: "STALE_QUIET", rule_text: "No report for the stale period, and no explicit resolution.", evidence_report_ids: [], evidence_quote: null }] } });
    wrap(<IntelligenceView i={i} />);
    const tl = screen.getByRole("list", { name: /lifecycle transitions/i });
    expect(within(tl).getAllByRole("listitem")).toHaveLength(3);
    expect(within(tl).getByText(/Confirmed → Stale/)).toBeInTheDocument();
    expect(within(tl).getByText(/caused by elapsed time, not by a new report/i)).toBeInTheDocument();
    expect(screen.getByText(/the event's last report, not the end of the data/i)).toBeInTheDocument();
  });

  it("says why velocity is not stated instead of inventing a rate", () => {
    const v = intel().velocity;
    wrap(<IntelligenceView i={intel({ velocity: { ...v, availability: "ABSTAINED", velocity_per_hour: null, source_growth: null, series: [], reason: "1 report(s): fewer than 3 are needed to state a pace." } })} />);
    const tile = screen.getByRole("group", { name: "Narrative velocity" });
    expect(tile).toHaveTextContent(/abstained/i);
    expect(tile).toHaveTextContent(/fewer than 3/i);
  });

  it("lists every report beneath the event and which are copies", async () => {
    const i = intel();
    i.group.reports[1] = { ...i.group.reports[1]!, independent: false, relation: "SYNDICATED" };
    wrap(<IntelligenceView i={i} />);
    const table = screen.getByRole("table", { name: /reports of this event/i });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText(/copy of another report/i)).toBeInTheDocument();
    expect(within(table).getByText("this report")).toBeInTheDocument();
  });

  it("opens the method drawer from the button and records it in the URL", async () => {
    wrap(<IntelligenceView i={intel()} />);
    await userEvent.click(screen.getByRole("button", { name: /how is this worked out/i }));
    const dlg = await screen.findByRole("dialog");
    expect(within(dlg).getByText(/closed list of cue phrases/i)).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("IntelligencePanel", () => {
  it("renders nothing and makes no request when the layer is off", () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    const { container } = wrap(<IntelligencePanel signalId="sig_a" enabled={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(f).not.toHaveBeenCalled();
  });

  it("fetches and shows the view, and a failure becomes a notice, not a crash", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(intel()), { status: 200, headers: { "content-type": "application/json" } })));
    const ok = wrap(<IntelligencePanel signalId="sig_a" enabled />);
    expect(await screen.findByText(/what is known about this event/i)).toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "Scope" })).toBeInTheDocument();
    ok.unmount();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "signal 'x' not found" }), { status: 404, headers: { "content-type": "application/json" } })));
    wrap(<IntelligencePanel signalId="x" enabled />);
    expect(await screen.findByText(/event intelligence is not available for this event/i)).toBeInTheDocument();
  });
});

describe("IntelligenceSummary", () => {
  it("is a compact result that links to the full view and names what was not claimed", () => {
    const i = intel({ abstentions: [{ field: "sector", state: "UNKNOWN", reason: "no sector is named or implied" }] });
    wrap(<IntelligenceSummary i={i} />);
    expect(screen.getByRole("link", { name: /open the full view/i })).toHaveAttribute("href", "/events/sig_a#intelligence");
    expect(screen.getByText(/not claimed: sector/i)).toBeInTheDocument();
    expect(screen.getByText(/moderate · 2 independent of 2/i)).toBeInTheDocument();
  });
});

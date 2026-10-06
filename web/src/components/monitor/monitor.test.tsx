import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChangeSet, EventMemory, EventState, MonitorStatus, RiskChange } from "../../api/types";
import { ChangesFeed } from "./ChangesFeed";
import { EventMemoryPanel, EventMemoryView } from "./EventMemoryPanel";

const wrap = (ui: React.ReactElement, path = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const T = "2026-09-20T12:00:00Z";
const state = (over: Partial<EventState> = {}): EventState =>
  ({
    event_id: "evt_1", anchor_signal_id: "sig_a", lead_signal_id: "sig_c", headline: "JPMorgan fined $920 million", as_of: T, tracked: true, member_count: 2, report_count: 3, independent_sources: 3,
    first_seen: T, last_seen: T, event_type: "REGULATORY_LEGAL", scope_type: "COMPANY", scope_value: "JPMorgan Chase", severity: 8, severity_band: "high", lifecycle: "ESCALATING",
    evidence_tier: "MODERATE", conflict: "NO_CONFLICT", velocity_per_hour: 1, portfolio_id: "pf", materiality: "HIGH", exposure_share: 0.3, stress_status: "COMPLETED", stress_pnl_pct: -0.034,
    stress_run_id: "run_1", clock_trusted: true, fingerprint: "abc", ...over,
  }) as EventState;

const change = (type: RiskChange["change_type"], over: Partial<RiskChange> = {}): RiskChange =>
  ({
    change_id: `chg_${type}`, event_id: "evt_1", change_type: type, mode: "REPLAY", cycle: 5, at: T, headline: "JPMorgan fined $920 million", summary: `summary of ${type}`, rule: "SEVERITY_UP (>= 1 points)",
    previous: state({ severity: 6 }), current: state(), changed_fields: [], supporting_evidence: [{ kind: "LIFECYCLE_TRANSITION", text: "probe expands to more desks", at: T, report_id: "r3", signal_id: "sig_c", source: "Wire C", rule: "ESCALATION_CUE" }],
    portfolio_impact: { portfolio_id: "pf", materiality_previous: "MEDIUM", materiality_current: "HIGH", exposure_share_previous: 0.2, exposure_share_current: 0.3, stress_pnl_pct_previous: -0.02, stress_pnl_pct_current: -0.034, label: "x" },
    provenance: [], ...over,
  }) as RiskChange;

const changes = (items: RiskChange[], over: Partial<ChangeSet> = {}): ChangeSet =>
  ({ version: "monitor-v1", mode: "REPLAY", availability: "AVAILABLE", reason: null, portfolio_id: null, cycle: 5, window: 1, from_at: T, to_at: T, tracked_events: 4, untracked_events: 9, excluded_untrusted_clock: 2, truncated: false,
     changes: items, counts: Object.fromEntries(items.map((c) => [c.change_type, 1])), labels: [], limitations: ["In the frozen replay each cluster's severity is fixed."], ...over }) as ChangeSet;

const status = (over: Partial<MonitorStatus> = {}): MonitorStatus =>
  ({ version: "monitor-v1", mode: "REPLAY", available: true, state: "OK", reason: null, live_enabled: false, live_state: null, live_source_mode: null, replay_cycles: 6, replay_step_hours: 12, replay_first: T, replay_last: T,
     tracked_floor: "severity >= 5", changes_logged: 0, labels: [], limitations: [], ...over }) as MonitorStatus;

const cycles = Array.from({ length: 6 }, (_, i) => ({ index: i, at: `2026-09-2${i}T12:00:00Z`, baseline: i === 0 }));

function stub(opts: { monitor?: boolean; items?: RiskChange[]; live?: boolean } = {}) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { monitor: opts.monitor ?? true } });
    if (url.startsWith("/api/monitor/status")) return json(url.includes("LIVE") ? status({ mode: "LIVE", available: false, state: "OFF", reason: "the live feed is off; REPLAY works without it" }) : status());
    if (url.startsWith("/api/monitor/cycles")) return json(cycles);
    if (url.startsWith("/api/monitor/changes")) return json(changes(opts.items ?? [change("EVENT_ESCALATED"), change("STRESS_CHANGED")]));
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

describe("ChangesFeed", () => {
  it("renders nothing where the monitor is not served", async () => {
    stub({ monitor: false });
    const { container } = wrap(<ChangesFeed />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("lists what changed, links each change to its event and keeps simulation apart from assessment", async () => {
    stub();
    wrap(<ChangesFeed />);
    await screen.findByText("summary of EVENT_ESCALATED");
    expect(screen.getAllByRole("link", { name: "JPMorgan fined $920 million" })[0]).toHaveAttribute("href", "/events/sig_c");
    expect(screen.getAllByText("Escalated")[0]).toBeInTheDocument();
    const stress = screen.getByText("summary of STRESS_CHANGED").closest("li") as HTMLElement;
    expect(within(stress).getByText("Scenario assumption")).toBeInTheDocument();           // the stress figure is labelled a scenario, not an assessment
    expect(within(stress).getByText(/−2\.00% → −3\.40% of the book/)).toBeInTheDocument();
    expect(screen.getByText(/never a new risk/i)).toBeInTheDocument();
    expect(screen.getByText(/2 with replay-assigned times never placed on a timeline/)).toBeInTheDocument();
  });

  it("shows the supporting evidence of a change on demand", async () => {
    stub();
    wrap(<ChangesFeed />);
    await screen.findByText("summary of EVENT_ESCALATED");
    await userEvent.click(screen.getAllByText(/Evidence \(1\)/)[0] as HTMLElement);
    expect(screen.getAllByText(/probe expands to more desks/)[0]).toBeInTheDocument();
  });

  it("filters by type of change", async () => {
    stub();
    wrap(<ChangesFeed />);
    await screen.findByText("summary of EVENT_ESCALATED");
    await userEvent.click(screen.getByRole("button", { name: /Stress changed/ }));
    expect(screen.queryByText("summary of EVENT_ESCALATED")).not.toBeInTheDocument();
    expect(screen.getByText("summary of STRESS_CHANGED")).toBeInTheDocument();
  });

  it("steps the replay clock", async () => {
    const calls = stub();
    wrap(<ChangesFeed />);
    await screen.findByText(/Cycle 5 of 5/);
    await userEvent.click(screen.getByRole("button", { name: /previous cycle/i }));
    await screen.findByText(/Cycle 4 of 5/);
    await waitFor(() => expect(calls.some((c) => c.includes("cycle=4"))).toBe(true));
  });

  it("says why the live mode is empty and offers the replay, which needs no internet", async () => {
    stub();
    wrap(<ChangesFeed />, "/?mode=LIVE");
    await screen.findByText("The live feed is not running.");
    expect(screen.getByText(/REPLAY works without it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show the replay instead/i }));
    await screen.findByText("summary of EVENT_ESCALATED");
  });

  it("limits a compact view and expands on request", async () => {
    stub({ items: ["EVENT_ESCALATED", "STRESS_CHANGED", "NEW_EVENT"].map((t) => change(t as RiskChange["change_type"])) });
    wrap(<ChangesFeed limit={2} />);
    await screen.findByText("summary of EVENT_ESCALATED");
    expect(screen.queryByText("summary of NEW_EVENT")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show all 3/i }));
    expect(screen.getByText("summary of NEW_EVENT")).toBeInTheDocument();
  });

  it("says when nothing changed", async () => {
    stub({ items: [] });
    wrap(<ChangesFeed />);
    await screen.findByText(/Nothing changed in this cycle/);
  });
});

const memory = (over: Partial<EventMemory> = {}): EventMemory =>
  ({
    version: "monitor-v1", event_id: "evt_1", anchor_signal_id: "sig_a", headline: "JPMorgan fined", availability: "AVAILABLE", reason: null, as_of: T, mode: "REPLAY", portfolio_id: "pf", clock_trusted: true, current: state(),
    items: [
      { at: "2026-09-20T09:00:00Z", kind: "REPORT", observation: "SOURCE_EVENT", label: "JPMorgan fined $920 million", detail: "The first report of the event.", update_kind: "NEW_EVENT", rule: "FIRST_REPORT", signal_id: "sig_a", report_id: "r1", source: "Wire A", independent: true, provenance: [] },
      { at: "2026-09-20T10:00:00Z", kind: "REPORT", observation: "SOURCE_EVENT", label: "JPMorgan fined in a spoofing probe", detail: "More coverage of what the earlier reports already said.", update_kind: "CONTINUATION", rule: "COPY:SYNDICATED", signal_id: "sig_a", report_id: "r2", source: "Wire B", independent: false, provenance: [] },
      { at: "2026-09-20T11:00:00Z", kind: "REPORT", observation: "SOURCE_EVENT", label: "probe expands to more desks", detail: "A report of the confirmed event describes it widening.", update_kind: "ESCALATION", rule: "LIFECYCLE:ESCALATION_CUE", signal_id: "sig_c", report_id: "r3", source: "Wire C", independent: true, provenance: [] },
      { at: "2026-09-20T11:00:00Z", kind: "STRESS", observation: "SCENARIO_ASSUMPTION", label: "Stress Changed", detail: "Modeled scenario P&L -2.00% -> -3.40% of the book.", update_kind: null, rule: "STRESS_MOVE", signal_id: "sig_c", report_id: null, source: null, independent: null, provenance: [] },
    ],
    history: [
      { cycle: 4, at: "2026-09-20T12:00:00Z", severity: 6, lifecycle: "CONFIRMED", evidence_tier: "WEAK", conflict: "NO_CONFLICT", materiality: "MEDIUM", exposure_share: 0.2, stress_pnl_pct: -0.02, report_count: 2, independent_sources: 2 },
      { cycle: 5, at: "2026-09-21T12:00:00Z", severity: 8, lifecycle: "ESCALATING", evidence_tier: "MODERATE", conflict: "NO_CONFLICT", materiality: "HIGH", exposure_share: 0.3, stress_pnl_pct: -0.034, report_count: 3, independent_sources: 3 },
    ],
    update_counts: { NEW_EVENT: 1, CONTINUATION: 1, ESCALATION: 1 }, signal_ids: ["sig_a", "sig_c"], labels: [], limitations: ["Events whose report times were assigned by the replay are never ordered."], ...over,
  }) as EventMemory;

describe("EventMemoryView", () => {
  it("shows the event as a narrative with each report classified and each statement labelled by what it is", () => {
    wrap(<EventMemoryView m={memory()} />);
    expect(screen.getByLabelText("Event timeline").querySelectorAll("li")).toHaveLength(4);
    for (const t of ["New event", "Continuation", "Escalation"]) expect(screen.getAllByText(new RegExp(`^${t}`)).length).toBeGreaterThan(0);
    expect(screen.getByText(/A copy or more of the same coverage is a continuation/i)).toBeInTheDocument();
    expect(screen.getAllByText("Source report").length).toBe(3);
    expect(screen.getAllByText("Scenario assumption").length).toBeGreaterThan(0);        // the stress item and the history column are both labelled
    expect(screen.getByText(/Wire B · copy/)).toBeInTheDocument();
    expect(screen.getByText(/Rule: LIFECYCLE:ESCALATION_CUE/)).toBeInTheDocument();
  });

  it("lists the history by cycle in a table whose scenario column says it is a scenario", async () => {
    wrap(<EventMemoryView m={memory()} />);
    await userEvent.click(screen.getByText(/History by monitoring cycle \(2\)/));
    const table = screen.getByRole("table", { name: /state at each monitoring cycle/i });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("Scenario assumption")).toBeInTheDocument();
    expect(within(table).getByText("−3.40%")).toBeInTheDocument();
  });

  it("explains an event whose times were assigned by the replay instead of inventing an order", () => {
    wrap(<EventMemoryView m={memory({ availability: "UNAVAILABLE", reason: "the report times of this event were assigned by the replay", items: [], history: [], current: null, clock_trusted: false })} />);
    expect(screen.getByText("This event's history cannot be followed.")).toBeInTheDocument();
    expect(screen.getByText(/assigned by the replay/)).toBeInTheDocument();
  });
});

describe("EventMemoryPanel", () => {
  it("is hidden where the monitor is not served", async () => {
    stub({ monitor: false });
    const { container } = wrap(<EventMemoryPanel signalId="sig_a" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("loads the timeline of the event", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/meta")) return json({ capabilities: { monitor: true } });
      if (url.startsWith("/api/events/sig_a/timeline")) return json(memory());
      return new Response(JSON.stringify({ detail: "nope" }), { status: 404 });
    }));
    wrap(<EventMemoryPanel signalId="sig_a" />);
    await screen.findByRole("heading", { name: "How this event developed" });
    await screen.findByLabelText("Event timeline");
  });
});

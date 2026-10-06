import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RiskSignal, WatchlistActivity, Watchlist, WatchVocabulary } from "../../api/types";
import { WatchButton } from "./WatchButton";
import { WatchlistEditor } from "./WatchlistEditor";
import { WatchlistsPanel } from "./WatchlistsPanel";

const wrap = (ui: React.ReactElement, path = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const T = "2026-09-20T12:00:00Z";
const vocab: WatchVocabulary = {
  companies: [{ value: "ENT_JPM", label: "JPMorgan Chase (JPM)", detail: "JPM" }, { value: "ENT_XOM", label: "Exxon Mobil (XOM)", detail: "XOM" }],
  sectors: [{ value: "Energy", label: "Energy", detail: null }, { value: "Financials", label: "Financials", detail: null }],
  industries: [{ value: "Banks", label: "Banks", detail: "Financials" }],
  geographies: [{ value: "US", label: "United States", detail: null }],
  event_types: [{ value: "REGULATORY_LEGAL", label: "Regulatory / Legal", detail: null }],
  risk_themes: [{ value: "rates", label: "Interest rates", detail: null }],
  portfolio_exposure: [{ value: "top:N", label: "Top N holdings by value (N up to 10)", detail: null }, { value: "ENT_JPM", label: "JPMorgan Chase (JPM)", detail: "JPM" }],
  max_watchlists: 20, max_items: 50,
} as WatchVocabulary;

const wl = (over: Partial<Watchlist> = {}): Watchlist =>
  ({ id: "wl_abc12345", name: "Energy and rates", enabled: true, created_at: T, updated_at: T, items: [{ kind: "SECTOR", value: "Energy", label: "Energy" }, { kind: "COMPANY", value: "ENT_XOM", label: "Exxon Mobil (XOM)" }], ...over }) as Watchlist;

const activity = (w: Watchlist): WatchlistActivity =>
  ({
    version: "watchlist-v1", watchlist: w, mode: "REPLAY", cycle: 5, window: 6, as_of: T, portfolio_id: "pf", status: "OK", reason: null, recent_changes: 1, provenance: [], labels: ["Matching reads the scope EventShock already resolved."], limitations: [],
    items: [
      { item: w.items[0], status: "MATCHED", reason: null, matched_events: 2, new_events: 1, scanned: 2, truncated: false,
        rollup: { max_severity: 7, lifecycle_counts: { CONFIRMED: 1, ESCALATING: 1 }, evidence_counts: { MODERATE: 2 }, conflicts_open: 1, max_materiality: "HIGH", worst_stress_pnl_pct: -0.031, novelty_counts: { NEW: 2 }, fastest_velocity_per_hour: 1.2 },
        events: [{ event_id: "evt_1", lead_signal_id: "sig_1", headline: "Gulf refinery shuts after fire", match_reason: "Energy is in the event's scope path (vocabulary)", first_seen: T, last_seen: T, is_new: true, severity: 7, lifecycle: "ESCALATING",
          novelty: "NEW", velocity_per_hour: 1.2, evidence_tier: "MODERATE", conflict: "CONFLICTED", materiality: "HIGH", exposure_share: 0.31, stress_pnl_pct: -0.031, recent_changes: ["EVENT_ESCALATED"], clock_trusted: true }] },
      { item: w.items[1], status: "NO_MATCH", reason: "no event in view matches this subject", matched_events: 0, new_events: 0, scanned: 0, truncated: false, events: [], rollup: null },
    ],
  }) as WatchlistActivity;

function stub(opts: { lists?: Watchlist[]; watch?: boolean } = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  let lists = opts.lists ?? [wl()];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { watchlists: opts.watch ?? true, monitor: true } });
    if (url.startsWith("/api/watchlists/vocabulary")) return json(vocab);
    if (/\/activity/.test(url)) return json(activity(lists[0] as Watchlist));
    if (url === "/api/watchlists" && method === "POST") { const w = wl({ id: "wl_new00001", name: body.name, items: body.items, enabled: body.enabled }); lists = [...lists, w]; return json(w, 201); }
    if (url === "/api/watchlists") return json({ watchlists: lists });
    if (/\/api\/watchlists\/wl_/.test(url) && method === "PUT") { const id = url.split("/").pop() as string; lists = lists.map((l) => (l.id === id ? { ...l, ...body } : l)); return json(lists.find((l) => l.id === id)); }
    if (/\/api\/watchlists\/wl_/.test(url) && method === "DELETE") { lists = lists.filter((l) => !url.endsWith(l.id)); return new Response(null, { status: 204 }); }
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

describe("WatchlistsPanel", () => {
  it("lists the watchlists with their items and inspects the activity of each item", async () => {
    stub();
    wrap(<WatchlistsPanel />);
    await screen.findByRole("heading", { name: "Energy and rates" });
    expect(within(screen.getByLabelText("Watched items")).getByText("Exxon Mobil (XOM)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /inspect activity/i }));
    const matched = await screen.findByLabelText("Sector Energy");
    expect(within(matched).getByText("2 events · 1 new")).toBeInTheDocument();
    expect(within(matched).getByRole("link", { name: "Gulf refinery shuts after fire" })).toHaveAttribute("href", "/events/sig_1");
    expect(within(matched).getByText(/Why it is here: Energy is in the event's scope path/)).toBeInTheDocument();
    expect(within(matched).getByText("Scenario assumption")).toBeInTheDocument();                 // the stress figure is a simulation, labelled
    expect(within(matched).getByText("Conflicting reports")).toBeInTheDocument();
    const none = screen.getByLabelText("Company Exxon Mobil (XOM)");
    expect(within(none).getByText("no event in view matches this subject")).toBeInTheDocument();
  });

  it("says plainly when there are no watchlists", async () => {
    stub({ lists: [] });
    wrap(<WatchlistsPanel />);
    await screen.findByText("No watchlists yet");
    expect(screen.getByText(/unresolved events never match one/i)).toBeInTheDocument();
  });

  it("switches a list off and deletes it only after a confirmation", async () => {
    const calls = stub();
    wrap(<WatchlistsPanel />);
    await screen.findByRole("heading", { name: "Energy and rates" });
    await userEvent.click(screen.getByRole("button", { name: /switch off/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && (c.body as { enabled: boolean }).enabled === false)).toBe(true));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});

describe("WatchlistEditor", () => {
  it("offers only the vocabulary and creates a watchlist", async () => {
    const calls = stub({ lists: [] });
    const done = vi.fn();
    wrap(<WatchlistEditor onDone={done} />);
    await userEvent.type(screen.getByLabelText("Name"), "Banks");
    await screen.findByRole("option", { name: "JPMorgan Chase (JPM)" });
    expect(screen.queryByRole("textbox", { name: /subject/i })).not.toBeInTheDocument();         // no free text for a subject
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "ENT_JPM");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(within(screen.getByLabelText("Watched items")).getByText(/JPMorgan Chase \(JPM\)/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "SECTOR");
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "Financials");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await userEvent.click(screen.getByRole("button", { name: "Create watchlist" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.body).toMatchObject({ name: "Banks", enabled: true, items: [{ kind: "COMPANY", value: "ENT_JPM" }, { kind: "SECTOR", value: "Financials" }] });
  });

  it("removes an item and does not duplicate one", async () => {
    stub();
    wrap(<WatchlistEditor initial={wl()} onDone={() => {}} />);
    await screen.findByRole("option", { name: "JPMorgan Chase (JPM)" });
    await userEvent.click(screen.getByRole("button", { name: "Remove Energy" }));
    expect(within(screen.getByLabelText("Watched items")).queryByText("Energy")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "SECTOR");
    await userEvent.selectOptions(screen.getByLabelText("Subject"), "Energy");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(within(screen.getByLabelText("Watched items")).getAllByText("Energy")).toHaveLength(1);
  });

  it("shows the server's reason when a subject is refused", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
      if (url.startsWith("/api/watchlists/vocabulary")) return json(vocab);
      if (init?.method === "POST") return json({ detail: [{ loc: ["body", "items"], msg: "COMPANY 'x' is not a company in the entity master", type: "watchlist.invalid" }] }, 422);
      return json({ detail: "nope" }, 404);
    }));
    wrap(<WatchlistEditor onDone={() => {}} />);
    await userEvent.type(screen.getByLabelText("Name"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Create watchlist" }));
    await screen.findByText(/is not a company in the entity master/);
  });
});

const signal = (over: Partial<RiskSignal> = {}): RiskSignal =>
  ({ id: "sig_1", entity: { entity_id: "ENT_XOM", entity_name: "Exxon Mobil", ticker: "XOM" }, scope: { level: "COMPANY", sector: "Energy" }, event: { status: "CLASSIFIED", category: "PRODUCT_OPERATIONS" }, ...over }) as RiskSignal;

describe("WatchButton", () => {
  it("offers only what EventShock resolved and adds it to the first watchlist", async () => {
    const calls = stub();
    wrap(<WatchButton s={signal()} eventType="PRODUCT_OPERATIONS" />);
    await userEvent.click(await screen.findByText("Watch this"));
    expect(screen.getByRole("button", { name: /add company: Exxon Mobil/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /add sector: Energy/i }));
    await screen.findByText(/Added to your watchlist/);
    const put = calls.find((c) => c.method === "PUT");
    expect((put?.body as { items: unknown[] }).items).toHaveLength(3);
  });

  it("offers no company for an unresolved event and nothing at all when nothing is resolved", async () => {
    stub();
    wrap(<WatchButton s={signal({ entity: { entity_id: "UNKNOWN_ENTITY" } as RiskSignal["entity"], scope: { level: "UNRESOLVED", sector: null } as RiskSignal["scope"] })} eventType="NO_EVENT" />);
    await screen.findByText("No resolved subject to watch for this event.");
    expect(screen.queryByText("Watch this")).not.toBeInTheDocument();
  });

  it("is hidden where watchlists are not served", async () => {
    stub({ watch: false });
    const { container } = wrap(<WatchButton s={signal()} />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Digest, DigestCard } from "../api/types";
import { drillTo } from "../lib/digest";
import { TodayPage } from "./TodayPage";

afterEach(() => vi.unstubAllGlobals());

const T = "2026-09-25T12:00:00Z";
const card = (over: Partial<DigestCard> = {}): DigestCard =>
  ({
    kind: "EVENT", section: "NEW_RISKS", rank: 1, rank_key: [{ name: "materiality", value: "HIGH" }, { name: "severity", value: "8" }, { name: "size of change", value: "8" }, { name: "recency", value: T }, { name: "id", value: "evt_1" }],
    event_id: "evt_1", signal_id: "sig_1", headline: "JPMorgan fined $920 million", summary: "New tracked risk: severity 8", change_types: ["NEW_EVENT"], change_ids: ["chg_1"], at: T, severity: 8, lifecycle: "ESCALATING", evidence_tier: "MODERATE",
    conflict: "NO_CONFLICT", materiality: "HIGH", exposure_share: 0.31, stress_pnl_pct: -0.034, independent_sources: 3,
    drill: ["EVENT", "EVIDENCE", "SCOPE", "EXPOSURE", "PROPAGATION", "STRESS", "ATTRIBUTION"].map((step) => ({ step, signal_id: "sig_1" })), overlap: null, watch: null, provenance: [], ...over,
  }) as DigestCard;

const section = (id: string, title: string, cards: DigestCard[], total = cards.length) => ({ id, title, blurb: "b", total, truncated: total > cards.length, cards });

const digest = (over: Partial<Digest> = {}): Digest =>
  ({
    version: "digest-v1", mode: "REPLAY", availability: "AVAILABLE", reason: null, cycle: 5, window: 4, as_of: T, portfolio_id: "default", portfolio_name: "Synthetic book", tracked_events: 40, change_count: 9,
    sections: [
      section("NEW_RISKS", "Top new risks", [card(), card({ rank: 2, event_id: "evt_2", signal_id: "sig_2", headline: "Oil jumps", rank_key: [{ name: "materiality", value: "MEDIUM" }] } as never), card({ rank: 3, event_id: "evt_3", signal_id: "sig_3", headline: "Third" } as never), card({ rank: 4, event_id: "evt_4", signal_id: "sig_4", headline: "Fourth risk" } as never)], 12),
      section("ESCALATIONS", "Escalations", []),
      section("CONCENTRATION", "Concentration changes", [card({ kind: "OVERLAP", section: "CONCENTRATION", event_id: null, headline: "Interest rates: 3 events now share it", summary: "3 events reach the same holdings", change_types: [], drill: [],
        overlap: { risk_factor: "RATES", risk_factor_label: "Interest rates", status: "NEW", event_count: 3, previous_event_count: 0, shared_share: 0.2, sentence: "s", signal_ids: ["sig_1"] } } as never)]),
      section("WATCHLISTS", "Watchlist activity", []),
    ],
    ranking: "Ordered by relevance to the portfolio (materiality tier), then severity, then the size of the change, then recency, then the event id. No importance score.",
    labels: ["Nothing here is scored"], limitations: ["A change is reported when a configured threshold is crossed."], ...over,
  }) as Digest;

function stub(opts: { monitor?: boolean; digest?: Digest; liveOff?: boolean } = {}) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { monitor: opts.monitor ?? true, explanations: true } });
    if (url.startsWith("/api/monitor/status")) return json(url.includes("LIVE") ? { mode: "LIVE", available: false, state: "OFF", reason: "the live feed is off; REPLAY works without it" } : { mode: "REPLAY", available: true, state: "OK", reason: null });
    if (url.startsWith("/api/monitor/cycles")) return json(Array.from({ length: 6 }, (_, i) => ({ index: i, at: `2026-09-2${i}T12:00:00Z`, baseline: i === 0 })));
    if (url.startsWith("/api/monitor/digest")) return json(url.includes("LIVE") ? digest({ mode: "LIVE", availability: "UNAVAILABLE", reason: "the live feed is off; REPLAY works without it", sections: [] }) : (opts.digest ?? digest()));
    if (url.startsWith("/api/monitor/changes")) return json({ mode: "REPLAY", availability: "AVAILABLE", changes: [], counts: {}, tracked_events: 0, untracked_events: 0, excluded_untrusted_clock: 0, truncated: false, labels: [], limitations: ["l"] });
    if (url.startsWith("/api/events/") && url.includes("explanation")) return json({ version: "x", subject: "PRIORITY", event_id: "evt_1", signal_id: "sig_1", headline: "Priority HIGH", level: "HIGH", availability: "AVAILABLE", unavailable_reason: null, reasons: [], kinds: {}, limitations: [], labels: ["l"] });
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

const page = (path = "/today") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes><Route path="/today" element={<TodayPage />} /></Routes></MemoryRouter></QueryClientProvider>);
};

describe("TodayPage", () => {
  it("answers the question, shows each section with its total, the ranking rule and no score", async () => {
    stub();
    page();
    await screen.findByRole("heading", { name: "What should I care about right now?" });
    const sec = await screen.findByRole("region", { name: /Top new risks/ });
    expect(within(sec).getByText("12")).toBeInTheDocument();                                         // the true total, beside a capped list
    expect(screen.getByText(/No importance score\./)).toBeInTheDocument();
    expect(screen.getByText(/40 tracked events, 9 changes in the last 4 cycles/)).toBeInTheDocument();
    expect(screen.queryByText(/importance:|score:/i)).not.toBeInTheDocument();
  });

  it("lists only the top three of a section until asked for the rest", async () => {
    stub();
    page();
    const sec = await screen.findByRole("region", { name: /Top new risks/ });
    expect(within(sec).getAllByRole("listitem").filter((li) => li.getAttribute("data-kind") === "EVENT")).toHaveLength(3);
    await userEvent.click(within(sec).getByRole("button", { name: /show all 4/i }));
    expect(within(sec).getByText("Fourth risk")).toBeInTheDocument();
    expect(within(sec).getByText(/the top 4 of 12/)).toBeInTheDocument();
  });

  it("shows the key a card was ranked by and the drill-down chain to the attribution", async () => {
    stub();
    page();
    const first = (await screen.findAllByRole("listitem")).find((li) => li.getAttribute("data-rank") === "1" && li.getAttribute("data-kind") === "EVENT") as HTMLElement;
    await userEvent.click(within(first).getByText("Why is this here, in this order?"));
    const key = within(first).getByLabelText("Ranking key");
    expect(within(key).getByText("materiality")).toBeInTheDocument();
    expect(within(key).getByText("HIGH")).toBeInTheDocument();
    expect(within(first).getByText(/not a score/i)).toBeInTheDocument();
    const drill = within(first).getByRole("navigation", { name: "Drill down" });
    expect(within(drill).getAllByRole("link").map((l) => l.textContent)).toEqual(["Event", "Evidence", "Scope", "Portfolio exposure", "Propagation", "Stress", "Attribution"]);
    expect(within(drill).getByRole("link", { name: "Evidence" })).toHaveAttribute("href", "/events/sig_1?cycle=5#evidence");
    expect(within(drill).getByRole("link", { name: "Attribution" })).toHaveAttribute("href", "/stress?signal=sig_1&run=1");
  });

  it("labels a stress figure as a scenario and opens the structured reasons for a card", async () => {
    const calls = stub();
    page();
    const first = (await screen.findAllByRole("listitem")).find((li) => li.getAttribute("data-rank") === "1" && li.getAttribute("data-kind") === "EVENT") as HTMLElement;
    expect(within(first).getByText("Scenario assumption")).toBeInTheDocument();
    await userEvent.click(within(first).getByText("Why is this here, in this order?"));
    await userEvent.click(within(first).getByRole("button", { name: /full reasons/i }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(calls.some((c) => c.includes("/api/events/evt_1/explanation?subject=PRIORITY"))).toBe(true));
  });

  it("shows a concentration overlap as its own kind of card, and an honest empty section", async () => {
    stub();
    page();
    const conc = await screen.findByRole("region", { name: /Concentration changes/ });
    expect(within(conc).getByText("New overlap")).toBeInTheDocument();
    expect(within(conc).getByText("Interest rates: 3 events now share it")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Escalations/ })).getByText("Nothing in this section for this window.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Watchlist activity/ })).getByText(/Create a watchlist on the Portfolios page/)).toBeInTheDocument();
  });

  it("steps the replay clock and asks for that cycle", async () => {
    const calls = stub();
    page();
    await screen.findByText(/Cycle 5 of 5/);
    await userEvent.click(screen.getByRole("button", { name: /previous cycle/i }));
    await screen.findByText(/Cycle 4 of 5/);
    await waitFor(() => expect(calls.some((c) => c.startsWith("/api/monitor/digest") && c.includes("cycle=4"))).toBe(true));
  });

  it("explains an unavailable live mode and offers the replay, which needs no internet", async () => {
    stub();
    page("/today?mode=LIVE");
    await screen.findByText("The live feed is not running.");
    expect(screen.getAllByText(/REPLAY works without it/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("button", { name: /show the replay instead/i }));
    await screen.findByRole("region", { name: /Top new risks/ });
  });

  it("says it is not available where the monitor is not served", async () => {
    stub({ monitor: false });
    page();
    await screen.findByText("Today is not available here.");
  });

  it("walks the product story from information to the decision brief", async () => {
    stub();
    page();
    await userEvent.click(await screen.findByText(/How it fits together/));
    const ol = screen.getByRole("list", { name: "From information to decision brief" });
    const names = within(ol).getAllByRole("listitem").map((li) => li.querySelector("p.font-medium")?.textContent);
    expect(names[0]).toBe("Information");
    expect(names[names.length - 1]).toBe("Decision brief");
    expect(names).toContain("Portfolio materiality");
    expect(names.indexOf("Stress")).toBeLessThan(names.indexOf("Attribution"));
  });
});

describe("drillTo", () => {
  it("keeps a replay moment in the link and never invents a new page", () => {
    expect(drillTo({ step: "SCOPE", signal_id: "s 1" }, "REPLAY", 7)).toBe("/events/s%201?cycle=7#intelligence");
    expect(drillTo({ step: "EXPOSURE", signal_id: "s" }, "LIVE", null)).toBe("/events/s#stress");
    expect(drillTo({ step: "STRESS", signal_id: "s" }, "REPLAY", 3)).toBe("/stress?signal=s&run=1");
  });
});

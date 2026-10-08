import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { factsLine, reasonTone } from "../lib/review";
import { ReviewPage } from "./ReviewPage";

const AS_OF = "2026-10-01T12:00:00Z";
const reason = (code: string, label: string, detail: string) => ({ code, label, detail });
const item = (over: Record<string, unknown> = {}) => ({
  event_id: "evt_a", signal_id: "sig_a", headline: "After Iran Says Strait of Hormuz Is Closed Again, Oil Risk Rises", scope_type: "MARKET", scope_value: null, severity: 8, severity_band: "high",
  materiality: "CRITICAL", exposure_share: 0.31, independent_sources: 1, report_count: 1, evidence_tier: "WEAK", conflict: "NO_CONFLICT", lifecycle: "DEVELOPING", stress_pnl_pct: -0.04, last_seen: AS_OF,
  reasons: [reason("SINGLE_SOURCE_HIGH_SEVERITY", "High severity, one source", "severity 8 (at least 7) reported by 1 independent source"), reason("MATERIAL_TO_BOOK", "Material to the book", "relevance to the book is CRITICAL, reaching 31.0% of the book")],
  rank_key: [{ name: "portfolio materiality tier", value: "CRITICAL" }, { name: "severity", value: "8" }, { name: "rules fired", value: "2" }],
  status: "OPEN", changed_since_review: false, decision: null, ...over,
});
const queue = (items: unknown[], over: Record<string, unknown> = {}) => ({
  version: "review-v1", label: "ANALYST REVIEW QUEUE: not ground truth", mode: "REPLAY", availability: "AVAILABLE", reason: null, as_of: AS_OF, portfolio_id: null, status_filter: "OPEN",
  counts: { open: items.length, reviewed: 1, dismissed: 0, in_queue: items.length + 1, tracked_events: 400 }, matching: items.length, items,
  ranking: "Ordered, not scored: portfolio materiality tier, then severity.", limitations: ["The rules are judgement priors."],
  rules: [{ code: "MATERIAL_TO_BOOK", label: "Material to the book", rule: "relevance to the book is HIGH or CRITICAL" }], ...over,
});

let state: { queue: unknown; decisions: unknown[] };
const posts: unknown[] = [];

beforeEach(() => {
  posts.length = 0;
  window.localStorage.clear();
  state = { queue: queue([item(), item({ event_id: "evt_b", signal_id: "sig_b", headline: "Bank denies funding rumour", reasons: [reason("CONFLICTED_CLAIMS", "Sources disagree", "claims conflict (conflicted)")] })]), decisions: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/meta")) return json({ profile: "replay", as_of: AS_OF, capabilities: { review: true } });
    if (url.includes("/api/review/queue")) return json(state.queue);
    if (url.endsWith("/api/review/decisions") && init?.method === "POST") {
      const body = JSON.parse(init.body as string);
      posts.push(body);
      return json({ decision_id: "rv_1", ...body, created_at: AS_OF, fingerprint: "f", headline: "h", label: "x" }, 201);
    }
    return json({ detail: "not found" }, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const mount = (path = "/review") =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <ReviewPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

describe("Review queue page", () => {
  it("lists the events with the rule that queued each, the values that fired it and how it was ordered", async () => {
    mount();
    const first = (await screen.findAllByRole("listitem", { name: /Strait of Hormuz/ }))[0]!;
    expect(within(first).getAllByText("High severity, one source").length).toBeGreaterThan(0);
    expect(within(first).getByText(/reported by 1 independent source/)).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: /Strait of Hormuz/ })).toHaveAttribute("href", "/events/sig_a");
    expect(within(first).getByText(/market · severity 8\/10 · 1 independent source · weak evidence · critical to the book \(31\.0%\)/)).toBeInTheDocument();
    await userEvent.click(within(first).getByText("Why this position?"));
    expect(within(first).getByText(/portfolio materiality tier:/)).toBeInTheDocument();
    expect(screen.getByText(/Ordered, not scored/)).toBeInTheDocument();
    expect(screen.getByText(/3 of 400 tracked events need a look \(2 open\)/)).toBeInTheDocument();
  });

  it("shows the status counts on the tabs and the rules behind the queue", async () => {
    mount();
    expect(await screen.findByRole("button", { name: /Open\s*2/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Reviewed\s*1/ })).toBeInTheDocument();
    await userEvent.click(screen.getByText("Why events are queued: the rules"));
    expect(screen.getByText("relevance to the book is HIGH or CRITICAL")).toBeInTheDocument();
  });

  it("records a decision with the note and the reviewer's name, and clears the note", async () => {
    mount();
    const card = (await screen.findAllByRole("listitem", { name: /Strait of Hormuz/ }))[0]!;
    await userEvent.type(screen.getByLabelText(/Your name on decisions/), "Priya");
    await userEvent.type(within(card).getByLabelText("Note (optional)"), "checked with the desk");
    await userEvent.click(within(card).getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => expect(posts).toEqual([{ event_id: "evt_a", status: "REVIEWED", note: "checked with the desk", analyst_id: "Priya" }]));
    expect(window.localStorage.getItem("eventshock-analyst")).toBe("Priya");
    await waitFor(() => expect(within(card).getByLabelText("Note (optional)")).toHaveValue(""));
  });

  it("dismisses without a note and sends no empty strings", async () => {
    mount();
    const card = (await screen.findAllByRole("listitem", { name: /Bank denies/ }))[0]!;
    await userEvent.click(within(card).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(posts).toEqual([{ event_id: "evt_b", status: "DISMISSED", note: null, analyst_id: null }]));
  });

  it("shows a reviewed event with who decided, when and why, offers to reopen it, and warns when it changed since", async () => {
    const decision = { decision_id: "rv_1", event_id: "evt_a", status: "REVIEWED", note: "confirmed", analyst_id: "priya", created_at: AS_OF, fingerprint: "f", headline: "h", label: "x" };
    state.queue = queue([item({ status: "REVIEWED", decision })], { status_filter: "REVIEWED" });
    mount("/review?status=REVIEWED");
    const card = (await screen.findAllByRole("listitem", { name: /Strait of Hormuz/ }))[0]!;
    expect(within(card).getByText(/Reviewed by/, { selector: "p" })).toHaveTextContent("Reviewed by priya");
    expect(within(card).getByText("confirmed")).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(posts[0]).toMatchObject({ event_id: "evt_a", status: "OPEN" }));
  });

  it("flags an event that was reviewed and has changed since", async () => {
    const decision = { decision_id: "rv_1", event_id: "evt_a", status: "DISMISSED", note: "noise", analyst_id: "priya", created_at: AS_OF, fingerprint: "f", headline: "h", label: "x" };
    state.queue = queue([item({ changed_since_review: true, decision, reasons: [reason("CHANGED_SINCE_REVIEW", "Changed since reviewed", "it was dismissed and its evidence has changed since")] })]);
    mount();
    expect(await screen.findByText(/Open again: it was dismissed by priya/)).toBeInTheDocument();
    expect(screen.getByText("noise")).toBeInTheDocument();
  });

  it("says so when nothing is waiting, and why the live queue is empty", async () => {
    state.queue = queue([]);
    mount();
    expect(await screen.findByText("Nothing is waiting for review.")).toBeInTheDocument();
    state.queue = queue([], { mode: "LIVE", availability: "UNAVAILABLE", reason: "the live feed is off" });
    const { unmount } = mount("/review?mode=LIVE");
    expect(await screen.findByText("the live feed is off")).toBeInTheDocument();
    unmount();
  });

  it("is not offered outside the replay profile", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ profile: "demo", as_of: AS_OF, capabilities: { review: false } }), { status: 200, headers: { "Content-Type": "application/json" } })));
    mount();
    expect(await screen.findByText("The review queue is not available here.")).toBeInTheDocument();
  });
});

describe("review helpers", () => {
  it("tones the reasons that most need a person", () => {
    expect(reasonTone("CONFLICTED_CLAIMS")).toBe("neg");
    expect(reasonTone("CHANGED_SINCE_REVIEW")).toBe("neg");
    expect(reasonTone("MATERIAL_TO_BOOK")).toBe("warn");
    expect(reasonTone("UNRESOLVED_HIGH_SEVERITY")).toBe("demo");
  });

  it("states the facts from the item's own fields, with no new claim", () => {
    expect(factsLine(item() as never)).toBe("market · severity 8/10 · 1 independent source · weak evidence · critical to the book (31.0%)");
    expect(factsLine(item({ scope_type: "COMPANY", scope_value: "JPMorgan Chase", severity: null, independent_sources: 3, materiality: "NONE", evidence_tier: "STRONG" }) as never)).toBe("company · JPMorgan Chase · 3 independent sources · strong evidence");
  });
});

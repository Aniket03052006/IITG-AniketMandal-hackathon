import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FeedbackStats } from "../../api/types";
import { FeedbackBar } from "./FeedbackBar";
import { FeedbackStatsTab } from "./FeedbackStatsTab";

const wrap = (ui: React.ReactElement) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const stats = (): FeedbackStats =>
  ({
    version: "feedback-v1", label: "ANALYST FEEDBACK — not ground truth, and not used to train or change any model", volume: 12, events: 5, analysts: 3,
    relevance: { type: "RELEVANCE", total: 6, by_value: { RELEVANT: 3, PARTIALLY_RELEVANT: 1, IRRELEVANT: 2 }, agreement: 0.5, at_least_partly_relevant: 0.667 },
    scope: { type: "SCOPE", total: 4, by_value: { CORRECT: 3, INCORRECT: 1 }, agreement: 0.75, at_least_partly_relevant: null },
    event: { type: "EVENT", total: 2, by_value: { CORRECT: 2 }, agreement: 1, at_least_partly_relevant: null },
    needs_review: 3, disagreements: 1, first_at: "2026-10-01T00:00:00Z", last_at: "2026-10-02T00:00:00Z",
    note: "These are counts of what analysts said. They are analyst feedback, not ground truth: EventShock does not learn from them.", limitations: ["Feedback is self-selected."],
  }) as FeedbackStats;

function stub(on = true) {
  const posts: { type: string; value: string; event_id: string; comment: string | null }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { feedback: on } });
    if (url === "/api/feedback" && init?.method === "POST") { const b = JSON.parse(String(init.body)); posts.push(b); return json({ feedback_id: "fb_1", ...b }, 201); }
    if (url.startsWith("/api/feedback/statistics")) return json(stats());
    return json({ detail: "nope" }, 404);
  }));
  return posts;
}

describe("FeedbackBar", () => {
  it("is hidden where feedback is not served", async () => {
    stub(false);
    const { container } = wrap(<FeedbackBar eventId="evt_1" />);
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("records only the answers given, one per type, with the comment, and says it is not ground truth", async () => {
    const posts = stub();
    wrap(<FeedbackBar eventId="evt_1" cycle={4} />);
    await userEvent.click(await screen.findByText("Give feedback on this event"));
    const send = screen.getByRole("button", { name: "Send feedback" });
    expect(send).toBeDisabled();                                                        // nothing chosen yet
    await userEvent.click(screen.getByRole("button", { name: "Partly" }));
    const scope = screen.getByRole("group", { name: "Is the scope right?" });
    await userEvent.click(within(scope).getByRole("button", { name: "Incorrect" }));
    await userEvent.type(screen.getByLabelText(/Comment/), "wrong Exxon entity");
    expect(send).toBeEnabled();
    await userEvent.click(send);
    await screen.findByText(/Recorded 2 answers/);
    expect(posts.map((p) => [p.type, p.value])).toEqual([["RELEVANCE", "PARTIALLY_RELEVANT"], ["SCOPE", "INCORRECT"]]);
    expect(posts.every((p) => p.event_id === "evt_1" && p.comment === "wrong Exxon entity")).toBe(true);
    expect(screen.getByText(/not ground truth and it does not change any model/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Partly" })).toHaveAttribute("aria-pressed", "false");              // the form is cleared after sending
  });

  it("lets an answer be taken back before sending", async () => {
    stub();
    wrap(<FeedbackBar eventId="evt_1" />);
    await userEvent.click(await screen.findByText("Give feedback on this event"));
    const b = screen.getByRole("button", { name: "Relevant" });
    await userEvent.click(b);
    expect(b).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(b);
    expect(b).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeDisabled();
  });
});

describe("FeedbackStatsTab", () => {
  it("shows volume, agreement per type and unresolved feedback, labelled as analyst feedback", async () => {
    stub();
    wrap(<FeedbackStatsTab />);
    await screen.findByText("Analyst feedback, not ground truth.");
    expect(within(screen.getByRole("group", { name: "Feedback volume" })).getByText("12")).toBeInTheDocument();
    const rel = screen.getByRole("group", { name: "Relevance agreement" });
    expect(within(rel).getByText("50%")).toBeInTheDocument();
    expect(within(rel).getByText(/67% at least partly relevant/)).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Scope agreement" })).getByText("75%")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Event agreement" })).getByText("100%")).toBeInTheDocument();
    const un = screen.getByRole("group", { name: "Unresolved feedback" });
    expect(within(un).getByText("3")).toBeInTheDocument();
    expect(within(un).getByText(/1 where analysts disagree/)).toBeInTheDocument();
    expect(screen.getByText(/EventShock does not learn from them/)).toBeInTheDocument();
  });
});

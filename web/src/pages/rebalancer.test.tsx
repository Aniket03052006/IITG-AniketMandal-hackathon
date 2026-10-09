import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { backtest, decisions, detail, lab, ledger, overview, params, timeline } from "../components/rebalancer/rebalancer.fixtures";
import { RebalancerPage } from "./RebalancerPage";

afterEach(() => vi.unstubAllGlobals());

function stub(opts: { capable?: boolean; bt?: ReturnType<typeof backtest>; available?: boolean; lab?: "AVAILABLE" | "STALE" | "UNAVAILABLE" } = {}) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    const tilt = Number(new URL(url, "http://x").searchParams.get("tilt") ?? 2);
    const p = params({ tilt, is_default: tilt === 2 });
    if (url.startsWith("/api/meta")) return json({ capabilities: { rebalancer: opts.capable ?? true, live_enabled: false } });
    if (url.startsWith("/api/rebalancer/overview")) return json(overview({ available: opts.available ?? true }));
    if (url.startsWith("/api/rebalancer/timeline")) return json(timeline({ params: p }));
    if (url.startsWith("/api/rebalancer/lab")) return json(lab(opts.lab ?? "AVAILABLE"));
    if (url.startsWith("/api/rebalancer/ledger")) return json(ledger());
    if (/\/api\/rebalancer\/cycles\/\d+\/decisions/.test(url)) return json(decisions({ index: Number(url.split("/cycles/")[1]!.split("/")[0]) }));
    if (url.startsWith("/api/rebalancer/cycles/")) return json(detail(Number(url.split("/cycles/")[1]!.split("?")[0]), { params: p }));
    if (url.startsWith("/api/rebalancer/backtest")) return json(opts.bt ?? backtest());
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

const page = (path = "/rebalancer") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><Routes><Route path="/rebalancer" element={<RebalancerPage />} /></Routes></MemoryRouter></QueryClientProvider>);
};

describe("RebalancerPage", () => {
  it("tells the story: the summary, the chart, the exact figures, the trades, the reasons, the rule and the back-test", async () => {
    stub();
    page();
    expect(await screen.findByRole("heading", { name: "Tactical index rebalancer" })).toBeInTheDocument();
    expect(await screen.findByRole("img", { name: /Stacked weights of 4 stocks over 3 cycles/ })).toBeInTheDocument();
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(within(summary).getByText("4 stocks")).toBeInTheDocument();
    expect(within(summary).getByText(/3 social posts left off/)).toBeInTheDocument();
    const table = await screen.findByRole("table", { name: /Weight of every stock/ });
    expect(within(table).getByRole("row", { name: /NVDA/ })).toHaveTextContent("31.00%");
    expect(within(table).getByRole("row", { name: /JPM/ })).toHaveTextContent("20.00%");
    expect(screen.getByRole("heading", { name: "What was traded" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Why NVDA holds this weight" })).toBeInTheDocument();
    expect(screen.getByText("Nvidia approves $150B buyback")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How the rule works" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Back-test" })).toBeInTheDocument();
  });

  it("names the reason each stock holds its weight, from the closed list", async () => {
    stub();
    page();
    const table = await screen.findByRole("table", { name: /Weight of every stock/ });
    expect(within(within(table).getByRole("row", { name: /NVDA/ })).getByText("Tilted up")).toBeInTheDocument();
    expect(within(within(table).getByRole("row", { name: /JPM/ })).getByText("Tilted down")).toBeInTheDocument();
    expect(within(within(table).getByRole("row", { name: /XOM/ })).getByText("No reports")).toBeInTheDocument();
  });

  it("picks the stock to explain when one is chosen", async () => {
    stub();
    page();
    const table = await screen.findByRole("table", { name: /Weight of every stock/ });
    await userEvent.click(within(within(table).getByRole("row", { name: /JPM/ })).getByRole("button"));
    expect(await screen.findByRole("heading", { name: "Why JPM holds this weight" })).toBeInTheDocument();
  });

  it("asks for the cycle the URL names and for what-if parameters, and says it is a what-if", async () => {
    const calls = stub();
    page("/rebalancer?tilt=5&cycle=1");
    expect(await screen.findByText("You are looking at a what-if.")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((u) => u.startsWith("/api/rebalancer/timeline") && u.includes("tilt=5"))).toBe(true));
    expect(calls.some((u) => u.startsWith("/api/rebalancer/cycles/1") && u.includes("tilt=5"))).toBe(true);
  });

  it("shows no what-if banner for the shipped parameters", async () => {
    stub();
    page();
    await screen.findByRole("img", { name: /Stacked weights/ });
    expect(screen.queryByText("You are looking at a what-if.")).toBeNull();
  });

  it("is honest when the back-test has not been built or is stale", async () => {
    stub({ bt: backtest("UNAVAILABLE") });
    const a = page();
    expect(await screen.findByText("No back-test has been built.")).toBeInTheDocument();
    a.unmount();
    stub({ bt: backtest("STALE") });
    page();
    expect(await screen.findByText("This back-test is out of date.")).toBeInTheDocument();
  });

  it("does not read a back-test inside the shuffled range as evidence", async () => {
    stub({ bt: backtest("AVAILABLE", 0.82) });
    page();
    expect(await screen.findByText(/within what shuffled sentiment produces by chance/)).toBeInTheDocument();
    expect(screen.getByText("About ten trading sessions.")).toBeInTheDocument();
  });

  it("explains itself when the server cannot rebalance", async () => {
    stub({ capable: false });
    page();
    expect(await screen.findByText("The rebalancer is not available here.")).toBeInTheDocument();
  });

  it("says there is nothing to rebalance when no report exists", async () => {
    stub({ available: false });
    page();
    expect(await screen.findByText("There is nothing to rebalance yet.")).toBeInTheDocument();
  });

  it("offers four views and opens on the index, so nothing that was there is hidden", async () => {
    stub();
    page();
    const tabs = await screen.findByRole("tablist", { name: "Rebalancer views" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["The index", "Trade decisions", "Strategy lab", "Ledger"]);
    expect(within(tabs).getByRole("tab", { name: "The index" })).toHaveAttribute("aria-selected", "true");
  });

  it("asks only for what the open view needs", async () => {
    const calls = stub();
    page();
    await screen.findByRole("table", { name: /Weight of every stock/ });
    expect(calls.some((u) => u.includes("/decisions"))).toBe(false);
    expect(calls.some((u) => u.startsWith("/api/rebalancer/lab") || u.startsWith("/api/rebalancer/ledger"))).toBe(false);
  });

  it("opens the trade decisions of the cycle the URL names, with the strategy and the what-if", async () => {
    const calls = stub();
    page("/rebalancer?tab=decisions&cycle=1&strategy=sentiment_risk&tilt=3");
    expect(await screen.findByRole("table", { name: /Every stock: weight before this cycle/ })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "NVDA: Buy 3.00 pp" })).toBeInTheDocument();
    const u = calls.find((c) => c.includes("/cycles/1/decisions"))!;
    expect(u).toContain("strategy=sentiment_risk");
    expect(u).toContain("tilt=3");
    expect(screen.getByRole("radio", { name: "Sentiment tilt + risk limits" })).toHaveAttribute("aria-checked", "true");
  });

  it("switching strategy puts it in the URL, and the baseline leaves the URL clean", async () => {
    const calls = stub();
    page("/rebalancer?tab=decisions");
    await screen.findByRole("table", { name: /Every stock: weight before this cycle/ });
    await userEvent.click(screen.getByRole("radio", { name: "Sentiment x impact (experimental)" }));
    await waitFor(() => expect(calls.some((u) => u.includes("/decisions") && u.includes("strategy=sentiment_impact"))).toBe(true));
    await userEvent.click(screen.getByRole("radio", { name: "Sentiment tilt (baseline)" }));
    await waitFor(() => expect(calls.filter((u) => u.includes("/decisions")).some((u) => !u.includes("strategy="))).toBe(true));
  });

  it("shows the strategy lab with its honesty banner, and says when it is stale", async () => {
    stub({ lab: "STALE" });
    page("/rebalancer?tab=lab");
    expect(await screen.findByText("This lab is out of date.")).toBeInTheDocument();
    expect(screen.getByText(/not evidence of skill/)).toBeInTheDocument();
  });

  it("shows the ledger", async () => {
    stub();
    page("/rebalancer?tab=ledger");
    expect(await screen.findByText(/Simulated: nothing here was sent to a broker/)).toBeInTheDocument();
    expect(screen.getByText("looks fine")).toBeInTheDocument();
  });
});

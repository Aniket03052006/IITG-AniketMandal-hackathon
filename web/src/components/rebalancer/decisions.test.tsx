import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApprovalBar } from "./ApprovalBar";
import { ConstraintBadge } from "./ConstraintBadge";
import { DecisionBoard } from "./DecisionBoard";
import { DecisionCard } from "./DecisionCard";
import { LedgerTable } from "./LedgerTable";
import { StrategyLab } from "./StrategyLab";
import { StrategyPicker } from "./StrategyPicker";
import { decisions, ledger, ledgerEntry, lab, STRATEGIES, timeline } from "./rebalancer.fixtures";
import { orderSeries } from "../../lib/rebalancer";

afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); });
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{ui}</QueryClientProvider>);
const tl = timeline();
const series = orderSeries(tl.constituents, tl.tickers);

describe("ConstraintBadge", () => {
  it("says the rule and the signed effect in words", () => {
    render(<ConstraintBadge effect={{ code: "SECTOR_CAP", effect: -0.0167 }} />);
    expect(screen.getByText("Sector cap")).toBeInTheDocument();
    expect(screen.getByText("-1.67 pp")).toBeInTheDocument();
  });
});

describe("DecisionCard", () => {
  const nvda = decisions().decisions.find((d) => d.ticker === "NVDA")!;
  const jpm = decisions().decisions.find((d) => d.ticker === "JPM")!;
  it("shows the trade, the explanation, the headline with its time, and the rule that held it back", () => {
    render(<DecisionCard d={nvda} accepted onAccept={() => undefined} selectable selected={false} id="c" />);
    expect(screen.getByRole("article", { name: "NVDA: Buy 3.00 pp" })).toBeInTheDocument();
    expect(screen.getByText(/Its sentiment score is \+0.30/)).toBeInTheDocument();
    expect(screen.getByText("Turnover cap")).toBeInTheDocument();
    expect(screen.getByText("Nvidia approves $150B buyback")).toBeInTheDocument();
    expect(screen.getByText("Evidence adequate")).toBeInTheDocument();
  });
  it("flags thin evidence, a stale report and conflicting reports in words", () => {
    render(<DecisionCard d={jpm} accepted onAccept={() => undefined} selectable selected={false} id="c" />);
    expect(screen.getByText("Thin evidence")).toBeInTheDocument();
    expect(screen.getByText(/Stale: 2.5 days old/)).toBeInTheDocument();
    expect(screen.getByText(/Reports disagree · 40% positive \/ 60% negative/)).toBeInTheDocument();
  });
  it("lets a reader include or leave out a trade", async () => {
    const onAccept = vi.fn();
    render(<DecisionCard d={nvda} accepted onAccept={onAccept} selectable selected={false} id="c" />);
    await userEvent.click(screen.getByRole("checkbox", { name: /Include in approval/ }));
    expect(onAccept).toHaveBeenCalledWith(false);
  });
  it("offers no checkbox for a stock that does not trade", () => {
    const hold = decisions().decisions.find((d) => d.side === "HOLD")!;
    render(<DecisionCard d={hold} accepted={false} onAccept={() => undefined} selectable={false} selected={false} id="c" />);
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("No trade")).toBeInTheDocument();
  });
});

describe("DecisionBoard + ApprovalBar", () => {
  function stubDecide(status = 200, body: unknown = ledgerEntry()) {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
    }));
    return calls;
  }

  it("shows the table with before, target and after, one card per trade and the stocks that hold", () => {
    wrap(<DecisionBoard proposal={decisions()} series={series} q={{}} />);
    const table = screen.getByRole("table", { name: /Every stock: weight before this cycle/ });
    expect(within(within(table).getByRole("row", { name: "NVDA" })).getByText("Buy 3.00 pp")).toBeInTheDocument();
    expect(within(within(table).getByRole("row", { name: "JPM" })).getByText("Sell 2.00 pp")).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: "NVDA" })).toHaveTextContent("34.00%");   // the target the turnover cap kept it from
    expect(screen.getAllByRole("article")).toHaveLength(3 + 1);   // three trades + the held stock inside its disclosure
    expect(screen.getByText("1 stock with no trade")).toBeInTheDocument();
  });

  it("sends the digest of the proposal it was looking at and records the approval", async () => {
    const calls = stubDecide();
    wrap(<DecisionBoard proposal={decisions()} series={series} q={{ tilt: 3 }} />);
    await userEvent.type(screen.getByLabelText("Your name"), "Aniket");
    await userEvent.type(screen.getByLabelText(/Note/), "checked the headlines");
    await userEvent.click(screen.getByRole("button", { name: "Approve all trades" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect(calls[0]!.url).toBe("/api/rebalancer/proposals/decision");
    expect(calls[0]!.body).toMatchObject({ action: "APPROVE", cycle_index: 2, strategy: "sentiment", tilt: 3, analyst: "Aniket", note: "checked the headlines", proposal_sha256: "a".repeat(64), accepted_tickers: null });
    expect(await screen.findByText(/Recorded in the ledger as entry/)).toBeInTheDocument();
  });

  it("sends only the trades that stay included", async () => {
    const calls = stubDecide();
    wrap(<DecisionBoard proposal={decisions()} series={series} q={{}} />);
    await userEvent.type(screen.getByLabelText("Your name"), "A");
    const aapl = screen.getByRole("article", { name: /AAPL/ });
    await userEvent.click(within(aapl).getByRole("checkbox"));
    expect(screen.getByText(/Approving/)).toHaveTextContent("2 of 3 trades");
    await userEvent.click(screen.getByRole("button", { name: "Approve 2 trades" }));
    await waitFor(() => expect(calls.length).toBe(1));
    expect((calls[0]!.body as { accepted_tickers: string[] }).accepted_tickers.sort()).toEqual(["JPM", "NVDA"]);
  });

  it("will not approve a selection that cannot be funded, and says why", async () => {
    stubDecide();
    wrap(<DecisionBoard proposal={decisions()} series={series} q={{}} />);
    await userEvent.type(screen.getByLabelText("Your name"), "A");
    await userEvent.click(within(screen.getByRole("article", { name: /JPM/ })).getByRole("checkbox"));
    await userEvent.click(within(screen.getByRole("article", { name: /AAPL/ })).getByRole("checkbox"));
    expect(screen.getByRole("alert")).toHaveTextContent(/paid for by a sell/);
    expect(screen.getByRole("button", { name: /Approve 1 trades/ })).toBeDisabled();
  });

  it("needs a name before it records anything", async () => {
    wrap(<DecisionBoard proposal={decisions()} series={series} q={{}} />);
    expect(screen.getByRole("button", { name: "Approve all trades" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("reports a refused decision (a changed proposal) without pretending it was saved", async () => {
    stubDecide(409, { detail: "the proposal has changed since it was shown; reload it and decide again" });
    wrap(<ApprovalBar proposal={decisions()} accepted={new Set(["NVDA", "JPM", "AAPL"])} q={{}} />);
    await userEvent.type(screen.getByLabelText("Your name"), "A");
    await userEvent.click(screen.getByRole("button", { name: "Approve all trades" }));
    expect(await screen.findByText("The decision was not recorded.")).toBeInTheDocument();
    expect(screen.getByText(/proposal has changed/)).toBeInTheDocument();
    expect(screen.queryByText(/Recorded in the ledger/)).toBeNull();
  });

  it("shows an earlier decision on this proposal, and says when it was made on an earlier version", () => {
    wrap(<ApprovalBar proposal={decisions({ latest_decision: ledgerEntry({ stale: true }) })} accepted={new Set()} q={{}} />);
    expect(screen.getByText("Decided on an earlier version")).toBeInTheDocument();
    expect(screen.getByText(/looks fine/)).toBeInTheDocument();
  });

  it("has nothing to approve when the proposal trades nothing", () => {
    const none = decisions({ buys: 0, sells: 0, holds: 4 });
    none.decisions.forEach((d) => { d.side = "HOLD"; d.trade = 0; d.after = d.before; });
    wrap(<ApprovalBar proposal={none} accepted={new Set()} q={{}} />);
    expect(screen.getByText(/trades nothing/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve/ })).toBeNull();
  });
});

describe("StrategyPicker", () => {
  it("marks experiments and disables a strategy that cannot be served, with the reason", async () => {
    const onChange = vi.fn();
    const list = STRATEGIES.map((s) => (s.id === "sentiment_impact" ? { ...s, available: false, reason: "needs risk inputs" } : s));
    render(<StrategyPicker strategies={list} value="sentiment_risk" onChange={onChange} />);
    expect(screen.getByText("Experimental")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Sentiment x impact/ })).toBeDisabled();
    await userEvent.click(screen.getByRole("radio", { name: "Sentiment tilt (baseline)" }));
    expect(onChange).toHaveBeenCalledWith("sentiment");
  });
});

describe("StrategyLab", () => {
  it("compares every strategy, with the verdict in words and the multiple-comparison warning", () => {
    render(<StrategyLab view={lab()} />);
    expect(screen.getByText("3 sessions: an illustration of the mechanics, not evidence of skill.")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Every strategy over the same sessions/ });
    expect(within(table).getAllByText("Within what shuffled scores give")).toHaveLength(3);
    expect(within(table).getByRole("row", { name: /Equal weight/ })).toHaveTextContent("no placebo");
    expect(screen.getByText(/The best cell is the luckiest cell/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Cumulative net return of 5 strategies over 3 sessions/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Report half-life by turnover cap/ })).toBeInTheDocument();
    expect(screen.getByText(/277/)).toBeInTheDocument();
  });
  it("marks the shipped setting in the sensitivity grid in words", () => {
    render(<StrategyLab view={lab()} />);
    expect(screen.getAllByText(/· shipped/).length).toBeGreaterThanOrEqual(1);
  });
  it("says when the lab is out of date, and when it has not been built", () => {
    const { unmount } = render(<StrategyLab view={lab("STALE")} />);
    expect(screen.getByText("This lab is out of date.")).toBeInTheDocument();
    unmount();
    render(<StrategyLab view={lab("UNAVAILABLE")} />);
    expect(screen.getByText("The strategy lab has not been built.")).toBeInTheDocument();
  });
});

describe("LedgerTable", () => {
  it("lists decisions, marks a stale one, and states that nothing was sent", () => {
    render(<LedgerTable view={ledger([ledgerEntry({ seq: 2, stale: true, action: "REJECT", note: "" }), ledgerEntry()])} />);
    expect(screen.getByText(/Simulated: nothing here was sent to a broker/)).toBeInTheDocument();
    expect(screen.getByText("Proposal changed since")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getAllByText("Approved").length).toBeGreaterThanOrEqual(1);
  });
  it("warns loudly when the hash chain is broken", () => {
    render(<LedgerTable view={ledger([ledgerEntry()], false)} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/hash chain is broken/);
  });
  it("says what to do when the ledger is empty", () => {
    render(<LedgerTable view={ledger([])} />);
    expect(screen.getByText("No decision has been recorded.")).toBeInTheDocument();
  });
});

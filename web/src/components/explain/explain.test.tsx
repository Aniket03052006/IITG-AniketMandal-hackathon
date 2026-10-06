import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Explanation, Reason } from "../../api/types";
import { WhyScenario } from "./InlineWhy";
import { ExplanationView } from "./ReasonList";
import { WhyButtons, WhyDrawers } from "./WhyDrawer";

const wrap = (ui: React.ReactElement, path = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

const reason = (code: string, kind: Reason["kind"], text: string): Reason => ({ code, kind, text, value: 1, unit: null, detail: null, source_ref: "propagation.materiality", provenance: [{ kind: "PRODUCT_RULE", source: "x", ref_id: "sig_1", as_of: null }] }) as Reason;

const expl = (over: Partial<Explanation> = {}): Explanation =>
  ({
    version: "explain-v1", subject: "PRIORITY", event_id: "evt_1", signal_id: "sig_1", headline: "Priority HIGH: relevance to the portfolio, then severity 8", level: "HIGH", availability: "AVAILABLE", unavailable_reason: null,
    reasons: [
      reason("MATERIALITY", "PRODUCT_RULE", "Relevance to the portfolio is HIGH: it reaches 31% of the book"),
      reason("SEVERITY", "MODEL_OUTPUT", "Severity 8 of 10: the transparent scorecard, a triage level"),
      reason("STRESS_SHOCK", "SCENARIO_ASSUMPTION", "Equity −10.0% market-wide, an assumption"),
      reason("STRESS_HISTORY", "HISTORICAL_OBSERVATION", "A move this large occurred in 2.0% of 21-session windows (a historical frequency, not a probability)"),
    ],
    kinds: { MODEL_OUTPUT: 1, PRODUCT_RULE: 1, SCENARIO_ASSUMPTION: 1, HISTORICAL_OBSERVATION: 1 }, limitations: ["Severity is not calibrated to outcomes."], labels: ["Each reason says what kind of statement it is."], ...over,
  }) as Explanation;

describe("ExplanationView", () => {
  it("groups the reasons by the kind of statement they are so none can be read as another", () => {
    wrap(<ExplanationView e={expl()} />);
    for (const name of ["Product rule", "Model output", "Scenario assumption", "Historical observation"]) {
      const g = screen.getByRole("region", { name });
      expect(within(g).getAllByRole("listitem")).toHaveLength(1);
    }
    expect(within(screen.getByRole("region", { name: "Model output" })).getByText(/transparent scorecard/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Scenario assumption" })).getByText(/an assumption/)).toBeInTheDocument();
    expect(screen.getByText(/not a probability/)).toBeInTheDocument();
    expect(screen.getByText("Priority HIGH: relevance to the portfolio, then severity 8")).toBeInTheDocument();
  });

  it("shows the structured code and where each reason was read from", () => {
    wrap(<ExplanationView e={expl()} />);
    expect(screen.getAllByText(/read from propagation.materiality/).length).toBe(4);
    expect(screen.getByText("MATERIALITY")).toBeInTheDocument();
  });

  it("never shows a generic 'AI determined' line and states an unavailable explanation plainly", () => {
    wrap(<ExplanationView e={expl({ availability: "UNAVAILABLE", unavailable_reason: "the event does not exist yet at this moment", reasons: [] })} />);
    expect(screen.getByText("Nothing to explain here.")).toBeInTheDocument();
    expect(screen.queryByText(/AI determined/i)).not.toBeInTheDocument();
  });

  it("says why a partial explanation has no reasons rather than showing a blank", () => {
    wrap(<ExplanationView e={expl({ availability: "PARTIAL", reasons: [], unavailable_reason: "No stress was run" })} />);
    expect(screen.getByText("No stress was run")).toBeInTheDocument();
  });

  it("keeps the limitations one click away", async () => {
    wrap(<ExplanationView e={expl()} />);
    await userEvent.click(screen.getByText("What this does not tell you"));
    expect(screen.getByText("Severity is not calibrated to outcomes.")).toBeInTheDocument();
  });
});

function stub(explanations = true) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    const json = (b: unknown, st = 200) => new Response(JSON.stringify(b), { status: st, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/meta")) return json({ capabilities: { explanations } });
    if (url.startsWith("/api/events/")) return json(expl({ subject: url.includes("STRESS") ? "STRESS" : "PRIORITY" }));
    if (url === "/api/scenarios/explanation") return json(expl({ subject: "LAB", headline: "Why “Mine” moves the portfolio −8.3% (a hypothetical, not a prediction)" }));
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

describe("Why drawers", () => {
  it("opens the structured explanation for a subject and fetches it only then", async () => {
    const calls = stub();
    wrap(<><WhyButtons subjects={["PRIORITY", "STRESS"]} /><WhyDrawers eventId="sig_1" subjects={["PRIORITY", "STRESS"]} /></>);
    await screen.findByRole("button", { name: /why this priority/i });
    expect(calls.some((c) => c.includes("/explanation"))).toBe(false);                 // nothing is fetched until it is asked for
    await userEvent.click(screen.getByRole("button", { name: /why this stress/i }));
    await screen.findByText(/Priority HIGH|relevance to the portfolio/);
    expect(calls.some((c) => c.includes("/api/events/sig_1/explanation?subject=STRESS"))).toBe(true);
  });

  it("is hidden where explanations are not served", async () => {
    stub(false);
    const { container } = wrap(<WhyButtons subjects={["PRIORITY"]} />);
    await vi.waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("lands on a drawer from the URL", async () => {
    stub();
    wrap(<WhyDrawers eventId="sig_1" subjects={["PRIORITY", "VISIBILITY"]} />, "/?open=why-priority");
    await screen.findByRole("dialog");
    expect((await screen.findAllByText(/relevance to the portfolio/i)).length).toBeGreaterThan(0);
  });
});

describe("WhyScenario", () => {
  it("explains a scenario result on demand with the request that produced it", async () => {
    const calls = stub();
    wrap(<WhyScenario req={{ scenario_type: "CUSTOM", assumptions: [{ kind: "EQUITY_MARKET", value: -0.1, target: null, rationale: "" }], name: "Mine", signal_id: null, portfolio_id: null, exposure_priors: false, force: false } as never} />);
    await userEvent.click(await screen.findByRole("button", { name: "Why this result?" }));
    await screen.findByText(/a hypothetical, not a prediction/);
    expect(calls.filter((c) => c === "POST /api/scenarios/explanation")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Hide the reasons" }));
    await userEvent.click(screen.getByRole("button", { name: "Why this result?" }));
    expect(calls.filter((c) => c === "POST /api/scenarios/explanation")).toHaveLength(1);        // asked once, not again
  });
});

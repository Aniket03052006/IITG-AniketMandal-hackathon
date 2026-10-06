import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BriefButton, BriefDrawer, BriefView } from "./BriefDrawer";

const brief = {
  version: "brief-v1", event_id: "evt_1", signal_id: "s1", headline: "Fed signals a cut", mode: "REPLAY", as_of: "2026-09-25T22:00:00Z", cycle: 3, portfolio_id: null, portfolio_name: "Synthetic book",
  note: "Template-written. Stress figures: SCENARIO SIMULATION — NOT A PREDICTION.", labels: ["NO SCENARIO RUN"],
  sources: [{ id: "report", kind: "SOURCE_EVENT", label: "The lead report", endpoint: "/api/signals/s1", ref_id: "s1", as_of: null }, { id: "market", kind: "EXTERNAL_MARKET_OBSERVATION", label: "External market view", endpoint: null, ref_id: null, as_of: null }],
  sections: [
    { id: "EXECUTIVE_SUMMARY", title: "EXECUTIVE SUMMARY", availability: "AVAILABLE", statements: [{ text: "A headline was read.", kind: "EVENTSHOCK_ASSESSMENT", source_refs: ["report"] }] },
    { id: "EXTERNAL_MARKET_VIEW", title: "EXTERNAL MARKET VIEW", availability: "UNAVAILABLE", statements: [{ text: "No relevant external prediction market identified.", kind: "EXTERNAL_MARKET_OBSERVATION", source_refs: ["market"] }] },
  ],
};

function wrap(ui: React.ReactNode, url = "/?open=brief") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter></QueryClientProvider>);
}
afterEach(() => vi.unstubAllGlobals());

describe("BriefView", () => {
  it("numbers the sections, names each statement's kind in words and links its sources", () => {
    wrap(<BriefView b={brief as never} />);
    expect(screen.getByRole("heading", { name: /1\. EXECUTIVE SUMMARY/ })).toBeTruthy();
    expect(screen.getByText("EventShock assessment")).toBeTruthy();
    expect(screen.getByText("No relevant external prediction market identified.")).toBeTruthy();
    expect(screen.getByLabelText("source 1")).toBeTruthy();
    expect(screen.getByText(/NOT A PREDICTION/)).toBeTruthy();
    expect(screen.getByText(/\(unavailable\)/)).toBeTruthy();
  });
});

describe("BriefButton / BriefDrawer", () => {
  it("hides the button where the brief is not served", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ capabilities: { executive_brief: false } }), { status: 200 })));
    wrap(<BriefButton />);
    await new Promise((r) => setTimeout(r, 30));
    expect(screen.queryByRole("button", { name: /executive brief/i })).toBeNull();
  });

  it("loads the brief only when the drawer is open and offers Markdown copy", async () => {
    const f = vi.fn(async (u: string) => new Response(JSON.stringify(String(u).includes("/meta") ? { capabilities: { executive_brief: true } } : brief), { status: 200 }));
    vi.stubGlobal("fetch", f);
    wrap(<BriefDrawer eventId="evt_1" />);
    await waitFor(() => expect(screen.getByText("Fed signals a cut")).toBeTruthy());
    expect(screen.getByRole("button", { name: /copy as markdown/i })).toBeTruthy();
    expect(f.mock.calls.some((c) => String(c[0]).includes("/events/evt_1/brief"))).toBe(true);
  });

  it("does not request the brief while closed", async () => {
    const f = vi.fn(async (u: string) => new Response(JSON.stringify(String(u).includes("/meta") ? { capabilities: { executive_brief: true } } : brief), { status: 200 }));
    vi.stubGlobal("fetch", f);
    wrap(<BriefDrawer eventId="evt_1" />, "/");
    await new Promise((r) => setTimeout(r, 40));
    expect(f.mock.calls.some((c) => String(c[0]).includes("/brief"))).toBe(false);
  });
});

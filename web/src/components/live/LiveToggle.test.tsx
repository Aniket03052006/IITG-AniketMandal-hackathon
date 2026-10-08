import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveStatus } from "../../api/types";
import { LiveToggle, deliveredBySource, liveSummary } from "./LiveToggle";

const AS_OF = "2026-10-01T12:00:00Z";
const choices = (captureOk = false, edgarOk = false) => [
  { kind: "both", label: "News + SEC filings (two live sources)", network: true, available: edgarOk, reason: edgarOk ? null : "EVENTSHOCK_SEC_CONTACT is not set" },
  { kind: "gdelt", label: "GDELT news feed (live)", network: true, available: true, reason: null },
  { kind: "edgar", label: "SEC EDGAR 8-K filings (live)", network: true, available: edgarOk, reason: edgarOk ? null : "EVENTSHOCK_SEC_CONTACT is not set" },
  { kind: "capture", label: "Simulated live (captured file, offline)", network: false, available: captureOk, reason: captureOk ? null : "no capture file at data/live/sample_capture.jsonl" },
];
const status = (over: Partial<LiveStatus> = {}): LiveStatus =>
  ({
    enabled: false, state: "OFF", source_mode: null, source_kind: null, source_choices: choices(), simulated: false, poll_interval_seconds: null,
    last_attempt_at: null, last_success_at: null, next_attempt_at: null, last_error: null, consecutive_failures: 0, fetched_total: 0, new_total: 0,
    updated_total: 0, fetched_by_adapter: {}, last_poll_note: null, quarantined_total: 0, live_signal_count: 0, seq: 0, retention_hours: 48, event_model: "tfidf", event_model_note: null,
    market_context_through: "2026-10-01", ...over,
  }) as LiveStatus;
const meta = (on: boolean, profile = "replay") => ({ profile, as_of: AS_OF, capabilities: { live_enabled: on } });

let server: { meta: unknown; live: LiveStatus; put?: { status: number; body: unknown } };
const puts: unknown[] = [];

beforeEach(() => {
  puts.length = 0;
  server = { meta: meta(false), live: status() };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/meta")) return json(server.meta);
    if (url.endsWith("/api/live/status")) return json(server.live);
    if (url.endsWith("/api/live/state") && init?.method === "PUT") {
      const body = JSON.parse(init.body as string);
      puts.push(body);
      if (server.put) return json(server.put.body, server.put.status);
      server.live = body.enabled
        ? status({ enabled: true, state: "IDLE", source_mode: "GDELT", source_kind: body.source ?? "gdelt" })
        : status();
      server.meta = meta(body.enabled);
      return json(server.live);
    }
    return json({ detail: "not found" }, 404);
  }));
});
afterEach(() => vi.unstubAllGlobals());

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LiveToggle />
    </QueryClientProvider>,
  );

describe("Live switch", () => {
  it("starts off, labelled, and turning it on asks the server for the chosen source", async () => {
    mount();
    const sw = await screen.findByRole("switch", { name: /Turn live on/ });
    expect(sw).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("Off")).toBeInTheDocument();
    await userEvent.click(sw);
    await waitFor(() => expect(screen.getByRole("switch", { name: "Turn live off" })).toHaveAttribute("aria-checked", "true"));
    expect(puts).toEqual([{ enabled: true, source: "gdelt" }]);
    expect(screen.getByText("Waiting for first poll")).toBeInTheDocument();
  });

  it("turns off again with enabled:false and says so", async () => {
    server.live = status({ enabled: true, state: "OK", source_mode: "GDELT", source_kind: "gdelt", live_signal_count: 3, last_success_at: AS_OF });
    server.meta = meta(true);
    mount();
    const sw = await screen.findByRole("switch", { name: "Turn live off" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    await userEvent.click(sw);
    await waitFor(() => expect(screen.getByRole("switch", { name: /Turn live on/ })).toHaveAttribute("aria-checked", "false"));
    expect(puts).toEqual([{ enabled: false, source: null }]);
  });

  it("does not claim to be on when the server refuses, and shows the reason", async () => {
    server.put = { status: 409, body: { detail: "no capture file at data/live/sample_capture.jsonl" } };
    mount();
    const sw = await screen.findByRole("switch", { name: /Turn live on/ });
    await userEvent.click(sw);
    expect(await screen.findByRole("alert")).toHaveTextContent("no capture file");
    expect(screen.getByRole("switch", { name: /Turn live on/ })).toHaveAttribute("aria-checked", "false");
  });

  it("offers an unavailable source disabled, with its reason", async () => {
    mount();
    await screen.findByRole("switch");
    const capture = screen.getByRole("radio", { name: /Simulated live/ });
    expect(capture).toBeDisabled();
    expect(screen.getByText(/no capture file at/)).toBeInTheDocument();
    expect(screen.getByText("makes outbound requests")).toBeInTheDocument();
  });

  it("renders nothing outside the replay profile", async () => {
    server.meta = meta(false, "demo");
    const { container } = mount();
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

describe("liveSummary", () => {
  it("names the state, and a capture as simulated", () => {
    expect(liveSummary(status())).toBe("Off");
    expect(liveSummary(status({ enabled: true, state: "OK" }))).toBe("On");
    expect(liveSummary(status({ enabled: true, state: "ERROR" }))).toBe("Source unreachable");
    expect(liveSummary(status({ enabled: true, state: "OK", simulated: true }))).toBe("On · simulated");
    expect(liveSummary(status({ enabled: true, state: "IDLE", simulated: true, last_success_at: AS_OF }))).toBe("Capture finished · simulated");
  });
});

describe("Live switch: source hints", () => {
  it("says an offline capture makes no news-feed requests, without claiming the whole app is offline", async () => {
    server.live = status({ source_choices: choices(true) });
    mount();
    await screen.findByRole("switch");
    expect(screen.getByText("reads a local file; no news-feed requests")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Simulated live/ })).toBeEnabled();
  });
});

describe("Live switch: the two live sources", () => {
  it("starts both sources by default when SEC filings are available, and says which delivered", async () => {
    server.live = status({ source_choices: choices(false, true) });
    mount();
    const sw = await screen.findByRole("switch", { name: /Turn live on, source: News \+ SEC filings/ });
    await userEvent.click(sw);
    await waitFor(() => expect(puts).toEqual([{ enabled: true, source: "both" }]));
  });

  it("offers SEC filings disabled with the missing-contact reason, and defaults to news", async () => {
    mount();
    await screen.findByRole("switch", { name: /Turn live on, source: GDELT/ });
    expect(screen.getByRole("radio", { name: /SEC EDGAR 8-K/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /two live sources/ })).toBeDisabled();
    expect(screen.getAllByText(/EVENTSHOCK_SEC_CONTACT is not set/).length).toBe(2);
  });

  it("lets the user pick the filings alone", async () => {
    server.live = status({ source_choices: choices(false, true) });
    mount();
    await userEvent.click(await screen.findByRole("radio", { name: /SEC EDGAR 8-K/ }));
    await userEvent.click(screen.getByRole("switch", { name: /Turn live on, source: SEC EDGAR/ }));
    await waitFor(() => expect(puts).toEqual([{ enabled: true, source: "edgar" }]));
  });

  it("shows what the last poll saw, so a quiet source is visibly working", async () => {
    server.live = status({ enabled: true, state: "OK", source_mode: "EDGAR", source_kind: "edgar", last_success_at: AS_OF, last_poll_note: "SEC filings: 100 listed, 43 in the last 6 h, 0 matched" });
    server.meta = meta(true);
    mount();
    expect(await screen.findByText("SEC filings: 100 listed, 43 in the last 6 h, 0 matched")).toBeInTheDocument();
  });

  it("names what each source delivered", () => {
    expect(deliveredBySource(status({ fetched_by_adapter: { "gdelt-live": 1200, "sec-edgar-live": 3 } }))).toBe("news 1,200 · SEC filings 3");
    expect(deliveredBySource(status())).toBe("");
  });
});

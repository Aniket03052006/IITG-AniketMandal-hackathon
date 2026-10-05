import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdjustHost } from "./AdjustDrawer";

const knob = (path: string, over: Record<string, unknown> = {}) => ({
  path, group: "scenario", label: path, description: "", kind: "number", unit: null, min: 1, max: 10, choices: [], default: 7, value: 7, adjusted: false, ...over,
});
const edge = (rf: string, id: string, w: number) => [
  knob(`propagation.risk_factors.${rf}.transmission.${id}.weight`, { group: "mapping", min: -1, max: 1, default: w, value: w, label: `${rf} / ${id}: weight` }),
  knob(`propagation.risk_factors.${rf}.transmission.${id}.enabled`, { group: "mapping", kind: "boolean", default: true, value: true, min: null, max: null }),
  knob(`propagation.risk_factors.${rf}.transmission.${id}.shock`, { group: "mapping", kind: "boolean", default: true, value: true, min: null, max: null }),
];
const state = (over: Record<string, unknown> = {}) => ({
  version: "default", count: 0, updated_at: null, risk_factors: ["OIL_ENERGY", "RATES", "REGULATION"], note: "Adjusted values are your own assumptions.", added_edges: [],
  knobs: [
    knob("propagation.generation.min_severity", { label: "Minimum severity to generate a scenario", unit: "1-10" }),
    knob("propagation.generation.min_materiality", { kind: "choice", choices: ["LOW", "MEDIUM", "HIGH", "CRITICAL"], default: "MEDIUM", value: "MEDIUM", min: null, max: null, label: "Minimum relevance" }),
    knob("propagation.concentration.min_share", { group: "relevance", label: "Concentration flag share", min: 0.01, max: 1, default: 0.2, value: 0.2 }),
    knob("intelligence.grouping.window_hours", { group: "intelligence", label: "Grouping window", min: 1, max: 720, default: 48, value: 48, unit: "hours" }),
    ...edge("RATES", "tech_long_duration", 0.5),
  ],
  ...over,
});

const wrap = (path = "/?open=adjust") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><AdjustHost /></MemoryRouter></QueryClientProvider>);
};
afterEach(() => vi.unstubAllGlobals());

function stub(opts: { validateOk?: boolean; initial?: Record<string, unknown> } = {}) {
  const calls: { method: string; url: string; body?: unknown }[] = [];
  let current = state(opts.initial);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
    if (url === "/api/meta") return json({ capabilities: { adjustments: true } });
    if (url === "/api/adjustments/validate") return json(opts.validateOk === false ? { ok: false, issues: [{ path: "propagation.generation.min_severity", message: "must be between 1 and 10" }] } : { ok: true, issues: [] });
    if (url === "/api/adjustments" && method === "PUT") {
      current = state({ count: Object.keys(body.values).length, version: "abc123", knobs: current.knobs.map((k) => (k.path in body.values ? { ...k, value: body.values[k.path], adjusted: true } : k)) });
      return json(current);
    }
    if (url.startsWith("/api/adjustments") && method === "DELETE") {
      current = state();
      return json(current);
    }
    if (url === "/api/adjustments/reset") { current = state(); return json(current); }
    if (url === "/api/adjustments") return json(current);
    return json({ detail: "nope" }, 404);
  }));
  return calls;
}

describe("Adjust drawer", () => {
  it("lists the settings with their defaults and bounds, grouped, and nothing adjusted", async () => {
    stub();
    wrap();
    const dlg = await screen.findByRole("dialog");
    expect(await within(dlg).findByText("Minimum severity to generate a scenario")).toBeInTheDocument();
    expect(within(dlg).getByText(/Nothing is adjusted/)).toBeInTheDocument();
    expect(within(dlg).getAllByText(/Default/)[0]).toHaveTextContent(/Default 7/);
    expect(within(dlg).getAllByText(/allowed 1 to 10/)[0]).toBeInTheDocument();
    for (const t of ["Scenarios", "Relevance", "Mapping", "Event intelligence"]) expect(within(dlg).getByRole("tab", { name: t })).toBeInTheDocument();
  });

  it("validates then saves a change, then shows it as adjusted with a way back", async () => {
    const calls = stub();
    wrap();
    const input = await screen.findByLabelText("Minimum severity to generate a scenario");
    await userEvent.clear(input);
    await userEvent.type(input, "8");
    await userEvent.click(screen.getByRole("button", { name: /save 1 change/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const order = calls.filter((c) => c.url.startsWith("/api/adjustments") && c.method !== "GET").map((c) => `${c.method} ${c.url}`);
    expect(order).toEqual(["POST /api/adjustments/validate", "PUT /api/adjustments"]); // checked before it is saved
    expect(calls.find((c) => c.method === "PUT")!.body).toEqual({ values: { "propagation.generation.min_severity": 8 } });
    expect(await screen.findByText(/Saved\. The side-cars were rebuilt/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /reset minimum severity to generate a scenario to its default/i })).toBeInTheDocument();
    expect(screen.getByText(/1 value is adjusted from the defaults/)).toBeInTheDocument();
  });

  it("does not save a value the server refuses and says which one", async () => {
    const calls = stub({ validateOk: false });
    wrap();
    const input = await screen.findByLabelText("Minimum severity to generate a scenario");
    await userEvent.clear(input);
    await userEvent.type(input, "99");
    await userEvent.click(screen.getByRole("button", { name: /save 1 change/i }));
    expect(await screen.findByText("must be between 1 and 10")).toBeInTheDocument();
    expect(screen.getByText("Not saved")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
  });

  it("does not send an empty number", async () => {
    const calls = stub();
    wrap();
    const input = await screen.findByLabelText("Minimum severity to generate a scenario");
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: /save 1 change/i }));
    expect(await screen.findByText("Enter a number.")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/adjustments/validate")).toBe(false);
  });

  it("discards an unsaved change and resets an adjusted one", async () => {
    const calls = stub({ initial: { count: 1, version: "x", knobs: state().knobs.map((k) => (k.path === "propagation.generation.min_severity" ? { ...k, value: 9, adjusted: true } : k)) } });
    wrap();
    const input = (await screen.findByLabelText("Minimum severity to generate a scenario")) as HTMLInputElement;
    expect(input.value).toBe("9");
    await userEvent.click(screen.getByRole("button", { name: /reset minimum severity to generate a scenario to its default/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.includes("propagation.generation.min_severity"))).toBe(true));
    await userEvent.type(await screen.findByLabelText("Minimum severity to generate a scenario"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(screen.getByRole("button", { name: /^save/i })).toBeDisabled();
  });

  it("edits the mapping table and adds an edge that is labelled as the user's", async () => {
    const calls = stub();
    wrap();
    await userEvent.click(await screen.findByRole("tab", { name: "Mapping" }));
    const w = await screen.findByLabelText("RATES tech_long_duration weight");
    await userEvent.clear(w);
    await userEvent.type(w, "0.8");
    await userEvent.selectOptions(screen.getByLabelText("Risk factor"), "REGULATION");
    await userEvent.type(screen.getByPlaceholderText("e.g. healthcare costs"), "Healthcare costs");
    await userEvent.type(screen.getByPlaceholderText("e.g. Healthcare"), "Healthcare");
    await userEvent.type(screen.getByLabelText(/Why \(shown beside the edge\)/), "Insurers pass costs on");
    await userEvent.click(screen.getByRole("button", { name: /add to my changes/i }));
    await userEvent.click(screen.getByRole("button", { name: /save 2 changes/i }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const values = (calls.find((c) => c.method === "PUT")!.body as { values: Record<string, unknown> }).values;
    expect(values["propagation.risk_factors.RATES.transmission.tech_long_duration.weight"]).toBe(0.8);
    expect(values["propagation.risk_factors.RATES.transmission.user_healthcare_costs"]).toBeUndefined();
    expect(values["propagation.risk_factors.REGULATION.transmission.user_healthcare_costs"]).toEqual({ kind: "SECTOR", key: "Healthcare", weight: 0.3, enabled: true, shock: true, rationale: "Insurers pass costs on" });
  });

  it("is closed unless the URL asks for it", () => {
    stub();
    wrap("/");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

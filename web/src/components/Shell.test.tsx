import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Shell } from "./Shell";

const meta = {
  app: "EventShock",
  profile: "replay",
  replay: { snapshot_id: "x" },
  as_of: "2026-10-01T12:00:00Z",
  trigger_threshold: 7,
  capabilities: { analyze: true, monitor: false, live_enabled: false, adjustments: false },
  taxonomy: [],
};

const width = (w: number) => Object.defineProperty(window, "innerWidth", { configurable: true, writable: true, value: w });

beforeEach(() => {
  width(1440);
  window.localStorage.clear();
  window.scrollTo = vi.fn(); // jsdom does not implement it; the Shell scrolls to the top on navigation
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/meta")) return json(meta);
      if (url.includes("/api/signals")) return json({ items: [], total: 0 });
      return json({ detail: "not found" }, 404);
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

function mount(path = "/stress") {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<Shell />}>
            <Route path="*" element={<p>page body</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const shell = () => document.querySelector(".app-shell") as HTMLElement;

describe("app frame: sidebar + top bar", () => {
  it("lists the places the server can serve in the sidebar, under their three groups", async () => {
    mount();
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Evidence" })).toBeInTheDocument());
    for (const name of ["Desk", "Analyze", "Event", "Stress Lab", "Portfolios", "Evidence"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    // monitor capability is off on this server: its link is absent, not disabled
    expect(within(nav).queryByRole("link", { name: "Today" })).toBeNull();
    for (const g of ["Monitor", "Investigate", "Trust"]) expect(within(nav).getByText(g)).toBeInTheDocument();
  });

  it("marks the current page in the sidebar and names it in the top bar", async () => {
    mount("/stress");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: "Stress Lab" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Desk" })).not.toHaveAttribute("aria-current");
    const bar = document.querySelector(".topbar") as HTMLElement;
    expect(within(bar).getByText("Stress Lab")).toBeInTheDocument();
    expect(within(bar).getByText("Investigate")).toBeInTheDocument();
  });

  it("keeps the top bar's tools: jump-to-anything and the theme switch", async () => {
    mount();
    const bar = document.querySelector(".topbar") as HTMLElement;
    expect(within(bar).getAllByRole("button", { name: "Jump to anything" }).length).toBeGreaterThan(0);
    expect(within(bar).getByRole("button", { name: /Switch to (dark|light) theme/ })).toBeInTheDocument();
  });

  it("opens the drawer from the menu button and closes it on Escape, the close button and navigation", async () => {
    const user = userEvent.setup();
    mount();
    const open = screen.getByRole("button", { name: "Open navigation" });
    expect(open).toHaveAttribute("aria-expanded", "false");
    expect(shell().dataset.drawer).toBe("false");

    await user.click(open);
    expect(open).toHaveAttribute("aria-expanded", "true");
    expect(shell().dataset.drawer).toBe("true");
    await user.keyboard("{Escape}");
    expect(shell().dataset.drawer).toBe("false");

    await user.click(open);
    await user.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(shell().dataset.drawer).toBe("false");

    await user.click(open);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    await user.click(within(nav).getByRole("link", { name: "Portfolios" }));
    await waitFor(() => expect(shell().dataset.drawer).toBe("false"));
  });

  it("collapses to an icon rail, keeps every link reachable by name, and remembers the choice", async () => {
    const user = userEvent.setup();
    mount();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(shell().dataset.collapsed).toBe("true");
    expect(window.localStorage.getItem("eventshock-sidebar")).toBe("collapsed");
    expect(within(nav).getByRole("link", { name: "Stress Lab" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(shell().dataset.collapsed).toBe("false");
    expect(window.localStorage.getItem("eventshock-sidebar")).toBe("expanded");
  });

  it("starts as an icon rail on a narrow laptop when nothing is saved", () => {
    width(1100);
    mount();
    expect(shell().dataset.collapsed).toBe("true");
  });

  it("starts from the saved choice", () => {
    window.localStorage.setItem("eventshock-sidebar", "collapsed");
    mount();
    expect(shell().dataset.collapsed).toBe("true");
  });

  it("still works when storage is blocked", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      mount();
      await user.click(screen.getByRole("button", { name: /(Collapse|Expand) sidebar/ }));
      expect(screen.getByRole("navigation", { name: "Primary" })).toBeInTheDocument();
    } finally {
      spy.mockRestore();
      set.mockRestore();
    }
  });
});

describe("rebalancer link", () => {
  it("is absent when the server cannot rebalance", async () => {
    mount("/stress");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Evidence" })).toBeInTheDocument());
    expect(within(nav).queryByRole("link", { name: "Rebalancer" })).toBeNull();
  });

  it("appears, and marks the current page, when the server can rebalance", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (b: unknown, s = 200) => new Response(JSON.stringify(b), { status: s, headers: { "Content-Type": "application/json" } });
      if (url.endsWith("/api/meta")) return json({ ...meta, capabilities: { ...meta.capabilities, rebalancer: true } });
      if (url.includes("/api/signals")) return json({ items: [], total: 0 });
      return json({ detail: "not found" }, 404);
    }));
    mount("/rebalancer");
    const nav = await screen.findByRole("navigation", { name: "Primary" });
    await waitFor(() => expect(within(nav).getByRole("link", { name: "Rebalancer" })).toHaveAttribute("aria-current", "page"));
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { applyTheme, parseTheme, resolveTheme } from "../lib/theme";
import { Drawer } from "./Drawer";
import { FlowRail } from "./FlowRail";
import { Tex } from "./Math";
import { KIND_META, KindBadge, KindLegend } from "./ProvenanceKind";
import { StateNotice } from "./StateNotice";
import { ThemeSwitch } from "./ThemeSwitch";

const wrap = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("theme", () => {
  it("is light by default whatever the system prefers, and ?theme= beats the stored choice", () => {
    expect(resolveTheme("", null)).toBe("light");
    expect(resolveTheme("", "dark")).toBe("dark");
    expect(resolveTheme("?theme=light", "dark")).toBe("light");
    expect(resolveTheme("?theme=dark", null)).toBe("dark");
    expect(resolveTheme("?theme=neon", "garbage")).toBe("light");
    expect(parseTheme("dark")).toBe("dark");
    expect(parseTheme(null)).toBeNull();
  });

  it("applies the theme to the document and toggles with a labelled button that stores the choice", async () => {
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    render(<ThemeSwitch />);
    const btn = await screen.findByRole("button", { name: "Switch to dark theme" });
    expect(screen.getByText("Light theme")).toBeInTheDocument();
    await userEvent.click(btn);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
    expect(window.localStorage.getItem("eventshock-theme")).toBe("dark");
    await userEvent.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("still toggles when storage is blocked", async () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<ThemeSwitch />);
    await userEvent.click(await screen.findByRole("button", { name: /Switch to/ }));
    expect(["light", "dark"]).toContain(document.documentElement.dataset.theme);
    spy.mockRestore();
    applyTheme("light");
  });
});

describe("FlowRail", () => {
  it("marks the current stage and links the rest", () => {
    wrap(<FlowRail active="impact" eventId="sig_1" context="Nike" />);
    const nav = screen.getByRole("navigation", { name: "EventShock chain" });
    expect(nav).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(5);
    expect(steps.map((s) => s.getAttribute("data-state"))).toEqual(["done", "done", "active", "todo", "todo"]);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("link", { name: "Stress" })).toHaveAttribute("href", "/stress?signal=sig_1");
    expect(screen.getByRole("link", { name: "Understand" })).toHaveAttribute("href", "/events/sig_1#understand");
  });

  it("scrolls in place on the event page instead of navigating", async () => {
    const go = vi.fn();
    wrap(<FlowRail active="event" eventId="sig_1" onNavigate={go} />);
    await userEvent.click(screen.getByRole("button", { name: "Impact" }));
    expect(go).toHaveBeenCalledWith("impact");
    expect(screen.getByRole("link", { name: "Stress" })).toBeInTheDocument();
  });
});

describe("provenance of a number", () => {
  it("names all four kinds in words (never colour alone), each with its meaning", () => {
    render(<KindLegend />);
    for (const k of Object.values(KIND_META)) {
      expect(screen.getByText(k.label)).toBeInTheDocument();
      expect(screen.getByText(k.says)).toBeInTheDocument();
    }
    expect(Object.keys(KIND_META).sort()).toEqual(["historical", "model", "realised", "scenario"]);
  });

  it("gives each kind its own pattern class", () => {
    const { container } = render(
      <>
        <KindBadge kind="model" />
        <KindBadge kind="historical" />
        <KindBadge kind="scenario" />
        <KindBadge kind="realised" />
      </>,
    );
    expect([...container.querySelectorAll(".kind")].map((e) => e.className.split(" ").find((c) => c.startsWith("kind-")))).toEqual(["kind-model", "kind-historical", "kind-scenario", "kind-realised"]);
  });
});

describe("StateNotice", () => {
  it("answers what happened, why and what to do next, in that order", () => {
    render(<StateNotice tone="warn" what="Company not identified" why="No company matched." next={<button>Do this</button>} />);
    const text = screen.getByRole("status").textContent ?? "";
    expect(text.indexOf("Company not identified")).toBeLessThan(text.indexOf("No company matched."));
    expect(text.indexOf("No company matched.")).toBeLessThan(text.indexOf("Do this"));
  });
});

describe("Drawer", () => {
  const Demo = ({ onClose = () => undefined }: { onClose?: () => void }) => (
    <Drawer open onClose={onClose} title="Inputs">
      <button>first</button>
      <button>last</button>
    </Drawer>
  );

  it("is a modal dialog with a labelled close button, and Escape / scrim close it", async () => {
    const onClose = vi.fn();
    wrap(<Demo onClose={onClose} />);
    expect(screen.getByRole("dialog", { name: "Inputs" })).toHaveAttribute("aria-modal", "true");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Close Inputs" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("keeps Tab inside the dialog", async () => {
    wrap(<Demo />);
    const last = screen.getByRole("button", { name: "last" });
    last.focus();
    await userEvent.tab();
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
    await userEvent.tab({ shift: true });
    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });
});

describe("Tex", () => {
  it("shows the plain reading first, then the typeset formula", async () => {
    render(<Tex tex={String.raw`I=\min(10,\lceil 10r\rceil)`} label="impact is the ceiling of ten times r" />);
    expect(screen.getByRole("math", { name: "impact is the ceiling of ten times r" })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector('[data-tex="ready"] .katex')).not.toBeNull());
  });
});

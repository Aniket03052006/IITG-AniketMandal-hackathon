import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { orderSeries } from "../../lib/rebalancer";
import { timeline } from "./rebalancer.fixtures";
import { WeightsChart } from "./WeightsChart";

const tl = timeline();
const series = orderSeries(tl.constituents, tl.tickers);
const mount = (over: Partial<Parameters<typeof WeightsChart>[0]> = {}) => {
  const props = { timeline: tl, series, view: "stack" as const, cycle: 1, onCycle: vi.fn(), focus: null, onFocus: vi.fn(), ...over };
  return { props, ...render(<WeightsChart {...props} />) };
};

describe("WeightsChart", () => {
  it("is an image whose label states the view, the span and the largest weight, and points to the exact figures", () => {
    mount();
    const img = screen.getByRole("img", { name: /Stacked weights of 4 stocks over 3 cycles/ });
    expect(img.getAttribute("aria-label")).toMatch(/largest weight is NVDA at 28\.00%/);
    expect(img.getAttribute("aria-label")).toMatch(/table below/);
  });
  it("prints every ticker beside its band, so colour is never the only signal", () => {
    const { container } = mount();
    const labels = [...container.querySelectorAll(".rb-ticker")].map((n) => n.textContent);
    expect(labels.sort()).toEqual(["AAPL", "JPM", "NVDA", "XOM"]);
  });
  it("draws one band per stock, filled from a token (never a colour literal)", () => {
    const { container } = mount();
    const bands = container.querySelectorAll("path.rb-band");
    expect(bands).toHaveLength(4);
    for (const b of bands) expect((b as SVGPathElement).style.fill).toContain("var(--color-sector-");
  });
  it("switches to lines in the active view and says so", () => {
    const { container } = mount({ view: "active" });
    expect(container.querySelectorAll("path.rb-band")).toHaveLength(0);
    expect(container.querySelectorAll("path.rb-line")).toHaveLength(4);
    expect(screen.getByRole("img").getAttribute("aria-label")).toMatch(/Active weights against the equal-weight benchmark/);
  });
  it("dims every stock except the focused one", () => {
    const { container } = mount({ focus: "NVDA" });
    expect(container.querySelectorAll('path.rb-band[data-dim="true"]')).toHaveLength(3);
    expect(container.querySelectorAll('.rb-label[data-dim="true"]')).toHaveLength(3);
  });
  it("moves the selected cycle with the arrow, Home and End keys and stays inside the range", () => {
    const { props } = mount({ cycle: 1 });
    const svg = screen.getByRole("img");
    fireEvent.keyDown(svg, { key: "ArrowRight" });
    expect(props.onCycle).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(svg, { key: "ArrowLeft" });
    expect(props.onCycle).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(svg, { key: "End" });
    expect(props.onCycle).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(svg, { key: "Home" });
    expect(props.onCycle).toHaveBeenLastCalledWith(0);
  });
  it("reports the focused stock when the pointer enters its label", () => {
    const { container, props } = mount();
    const label = [...container.querySelectorAll(".rb-label")].find((g) => g.textContent === "JPM")!;
    fireEvent.pointerOver(label);
    expect(props.onFocus).toHaveBeenCalledWith("JPM");
  });
  it("says what it cannot draw instead of drawing nothing", () => {
    render(<WeightsChart timeline={timeline({ cycles: [] })} series={series} view="stack" cycle={0} onCycle={() => {}} focus={null} onFocus={() => {}} />);
    expect(screen.getByText(/Too few cycles/)).toBeInTheDocument();
  });
});

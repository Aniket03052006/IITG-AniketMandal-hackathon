import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { graph } from "../../lib/contagion.test";
import { ContagionMap } from "./ContagionMap";

describe("ContagionMap", () => {
  it("describes itself in words and draws every node as a labelled, focusable box", () => {
    render(<ContagionMap g={graph()} />);
    expect(screen.getByRole("group", { name: /one event reaches 2 risk factors, which land on 4 parts of the book, and 3 of the 3 holdings reached are shown/ })).toBeInTheDocument();
    const boxes = screen.getAllByRole("img");
    expect(boxes).toHaveLength(1 + 2 + 4 + 3);
    expect(boxes.every((b) => b.getAttribute("tabindex") === "0")).toBe(true);
    expect(screen.getByRole("img", { name: "Consumer, 36.0% of the book" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^After Iran Says Strait of Hormuz.*About: trade and conflict · Middle East/ })).toBeInTheDocument();
  });

  it("gives every line a tooltip with its status, its weight, its evidence and the rule that made it", () => {
    const { container } = render(<ContagionMap g={graph()} />);
    const titles = [...container.querySelectorAll("path title")].map((t) => t.textContent ?? "");
    expect(titles.some((t) => t.includes("Geopolitical risk → Equity positions: scenario assumption, weight +1.00 (hurts it). risk-off [equities_risk_off]"))).toBe(true);
    expect(titles.some((t) => t.includes("Geopolitical risk → Energy: scenario assumption, weight -0.50 (benefits it)"))).toBe(true);
    expect(titles.some((t) => t.includes("Oil and energy prices → Consumer: your assumption"))).toBe(true);
  });

  it("styles a line by its status and its sign, so a fact, an assumption and your assumption look different", () => {
    const { container } = render(<ContagionMap g={graph()} />);
    const edge = (title: string) => [...container.querySelectorAll("path")].find((p) => p.querySelector("title")?.textContent?.startsWith(title))!;
    const eq = edge("Geopolitical risk → Equity positions");
    expect(eq.getAttribute("data-tone")).toBe("hurts");
    expect(eq.getAttribute("stroke-dasharray")).toBe("7 5");
    expect(edge("Geopolitical risk → Energy").getAttribute("data-tone")).toBe("benefits");
    expect(edge("Oil and energy prices → Consumer").getAttribute("stroke-dasharray")).toBe("2 4");
    const fact = [...container.querySelectorAll("path")].find((p) => p.getAttribute("data-origin") === "held")!;
    expect(fact.getAttribute("stroke-dasharray")).toBeNull();
  });

  it("follows a box's lines on focus and says what they are, then lets go", async () => {
    const { container } = render(<ContagionMap g={graph()} />);
    const status = container.querySelector("[aria-live]")!;
    expect(status.textContent).toBe("");
    await userEvent.tab();
    const first = document.activeElement as SVGElement;
    expect(first.getAttribute("data-kind")).toBe("event");
    const dim = () => [...container.querySelectorAll("path[data-dim='true']")].length;
    expect(dim()).toBeGreaterThan(0); // the other lines fade
    expect(status.textContent).toContain("→");
    act(() => first.blur());
    expect(dim()).toBe(0);
  });

  it("offers a legend and a note when only the largest holdings are shown", () => {
    render(<ContagionMap g={graph({ reached: [...graph().reached, ...Array.from({ length: 20 }, (_, i) => ({ ...graph().reached[0]!, asset_id: `X${i}` }))] })} />);
    const legend = screen.getByRole("list", { name: "How to read the map" });
    expect(within(legend).getByText(/a configured assumption, not measured/)).toBeInTheDocument();
    expect(within(legend).getByText("hurts")).toBeInTheDocument();
    expect(screen.getByText(/The 3 largest of 23 holdings reached are shown/)).toBeInTheDocument();
  });

  it("draws nothing when the graph abstained", () => {
    const { container } = render(<ContagionMap g={graph({ availability: "ABSTAINED" })} />);
    expect(container).toBeEmptyDOMElement();
  });
});

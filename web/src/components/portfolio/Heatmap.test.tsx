import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CrossTab } from "../../api/types";
import { Heatmap } from "./Heatmap";

const exposure: CrossTab = {
  unit: "market_value", row_label: "Sector", col_label: "Asset class", total: 1_000_000, sum: 1_000_000, residual: 0, reconciled: true,
  rows: [{ key: "Fin", label: "Financials", total: 600_000 }, { key: "Tech", label: "Technology", total: 400_000 }],
  cols: [{ key: "EQUITY", label: "equity", total: 600_000 }, { key: "BOND", label: "bond", total: 200_000 }, { key: "CASH", label: "cash", total: 200_000 }],
  cells: [
    { row: "Fin", col: "EQUITY", value: 400_000, position_count: 3 }, { row: "Fin", col: "BOND", value: 200_000, position_count: 1 },
    { row: "Tech", col: "EQUITY", value: 200_000, position_count: 2 }, { row: "Tech", col: "CASH", value: 200_000, position_count: 1 },
  ],
};
const loss: CrossTab = {
  unit: "pnl", row_label: "Sector", col_label: "Market factor", total: -43, sum: -43, residual: 0, reconciled: true,
  rows: [{ key: "Fin", label: "Financials", total: -40 }, { key: "Tech", label: "Technology", total: -3 }],
  cols: [{ key: "EQUITY_PCT", label: "Equity price", total: -35 }, { key: "RATE_BP", label: "Interest rates", total: -8 }],
  cells: [
    { row: "Fin", col: "EQUITY_PCT", value: -30, position_count: 2 }, { row: "Fin", col: "RATE_BP", value: -10, position_count: 1 },
    { row: "Tech", col: "EQUITY_PCT", value: -5, position_count: 1 }, { row: "Tech", col: "RATE_BP", value: 2, position_count: 1 },
  ],
};

describe("Heatmap", () => {
  it("is a real table with row and column headers, asset classes named for people, and the numbers in the cells", () => {
    render(<Heatmap tab={exposure} title="Where the value sits" unitLabel="share of the whole book" />);
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Equities" })).toBeInTheDocument(); // the API's "equity" is shown as the app names it
    expect(within(table).getByRole("rowheader", { name: "Financials" })).toBeInTheDocument();
    const fin = within(table).getByRole("row", { name: /Financials/ });
    expect(within(fin).getByText("40.0%")).toBeInTheDocument(); // 400,000 of the 1,000,000 book
    expect(within(fin).getAllByText("60.0%").length).toBeGreaterThan(0); // its row total
  });

  it("leaves an empty cell visibly empty and says so to a screen reader, and tints the rest by their size", () => {
    render(<Heatmap tab={exposure} title="t" unitLabel="u" />);
    const empty = screen.getAllByText("none");
    expect(empty).toHaveLength(2 * 3 - 4); // 6 cells, 4 filled
    const cells = [...document.querySelectorAll<HTMLElement>(".heat-cell")];
    expect(cells).toHaveLength(4);
    const heats = cells.map((c) => Number(c.style.getPropertyValue("--heat")));
    expect(Math.max(...heats)).toBe(1); // the largest cell is the darkest
    expect(heats.filter((h) => h === 0.5)).toHaveLength(3); // the 200k cells are half of it
    expect(cells.every((c) => c.dataset.tone === "acc")).toBe(true);
  });

  it("gives every cell a tooltip with the amount and the positions behind it", () => {
    render(<Heatmap tab={exposure} title="t" unitLabel="u" />);
    expect(document.querySelector('[title="Financials × Equities: $400,000 (40.0% of the book), 3 positions"]')).not.toBeNull();
    expect(document.querySelector('[title^="Financials × Bonds"]')?.getAttribute("title")).toContain("1 position");
  });

  it("shows a loss as signed money, darkest where the loss is largest, and a gain in its own tone", () => {
    render(<Heatmap tab={loss} title="Where each shock landed" unitLabel="modeled change" />);
    const cells = [...document.querySelectorAll<HTMLElement>(".heat-cell")];
    const byText = (t: string) => cells.find((c) => c.textContent === t)!;
    expect(byText("−$30").dataset.tone).toBe("neg");
    expect(byText("+$2").dataset.tone).toBe("pos");
    expect(Number(byText("−$30").style.getPropertyValue("--heat"))).toBe(1);
    expect(screen.getByText("Interest rates")).toBeInTheDocument();
  });

  it("says the cells add up to the total they break down", () => {
    render(<Heatmap tab={loss} title="t" unitLabel="u" />);
    expect(screen.getByRole("status")).toHaveTextContent("The cells add up to −$43; the run's total change is −$43 (difference 0.00).");
    render(<Heatmap tab={exposure} title="t2" unitLabel="u" />);
    expect(screen.getAllByRole("status")[1]).toHaveTextContent("The cells add up to $1.0M; the book's total value is $1.0M");
  });

  it("draws nothing for a table with nothing in it", () => {
    const { container } = render(<Heatmap tab={{ ...loss, rows: [], cols: [], cells: [] }} title="t" unitLabel="u" />);
    expect(container).toBeEmptyDOMElement();
  });
});

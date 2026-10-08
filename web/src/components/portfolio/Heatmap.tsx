import type { CrossTab } from "../../api/types";
import { ASSET_CLASS_LABEL, money, moneyFull, pct } from "../../lib/format";
import { Check } from "../icons";

type Cell = { value: number; count: number };

/** The tint of a cell: how large it is next to the largest cell. A table without it would still be readable: the numbers carry the meaning. */
const heat = (value: number, max: number): number => (max > 0 ? Math.min(1, Math.abs(value) / max) : 0);

/**
 * Two dimensions at once, as a table. Exposure: how much of the book sits where (share of the whole book, so rows and columns read against
 * the one-way breakdowns above). Loss: where each shock landed (modeled change, so the largest losses are the darkest). Every cell
 * prints its number, the margins print the totals, and the footer says the cells add up: colour is reinforcement, never the only signal.
 */
export function Heatmap({ tab, title, unitLabel }: { tab: CrossTab; title: string; unitLabel: string }) {
  const isPnl = tab.unit === "pnl";
  const cells = new Map<string, Cell>(tab.cells.map((c) => [`${c.row}\u0000${c.col}`, { value: c.value, count: c.position_count }]));
  const max = Math.max(...tab.cells.map((c) => Math.abs(c.value)), 0);
  const colLabel = (k: string, label: string) => (tab.unit === "market_value" ? (ASSET_CLASS_LABEL[k] ?? label) : label);
  const fmt = (v: number) => (isPnl ? money(v, { signed: true }) : pct(v / (tab.total || 1), 1));
  const full = (v: number) => (isPnl ? moneyFull(v) : `${moneyFull(v)} (${pct(v / (tab.total || 1), 1)} of the book)`);
  if (tab.rows.length === 0 || tab.cols.length === 0) return null;
  return (
    <figure className="heat" aria-label={title}>
      <figcaption className="mb-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="ml-2 text-xs text-muted">{unitLabel}</span>
      </figcaption>
      <div className="heat-scroll">
        <table className="heat-table">
          <thead>
            <tr>
              <th scope="col" className="heat-corner">
                {tab.row_label} · {tab.col_label}
              </th>
              {tab.cols.map((c) => (
                <th key={c.key} scope="col" title={colLabel(c.key, c.label)}>
                  {colLabel(c.key, c.label)}
                </th>
              ))}
              <th scope="col" className="heat-total">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {tab.rows.map((r) => (
              <tr key={r.key}>
                <th scope="row" title={r.label}>
                  {r.label}
                </th>
                {tab.cols.map((c) => {
                  const cell = cells.get(`${r.key}\u0000${c.key}`);
                  if (!cell) {
                    return (
                      <td key={c.key} className="heat-empty">
                        <span aria-hidden="true">·</span>
                        <span className="sr-only">none</span>
                      </td>
                    );
                  }
                  const tone = isPnl ? (cell.value < 0 ? "neg" : "pos") : "acc";
                  return (
                    <td
                      key={c.key}
                      className="heat-cell num"
                      data-tone={tone}
                      style={{ "--heat": heat(cell.value, max).toFixed(3) } as React.CSSProperties}
                      title={`${r.label} × ${colLabel(c.key, c.label)}: ${full(cell.value)}, ${cell.count} ${cell.count === 1 ? "position" : "positions"}`}
                    >
                      {fmt(cell.value)}
                    </td>
                  );
                })}
                <td className="heat-total num">{fmt(r.total)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" className="heat-total">
                Total
              </th>
              {tab.cols.map((c) => (
                <td key={c.key} className="heat-total num">
                  {fmt(c.total)}
                </td>
              ))}
              <td className="heat-total num">{fmt(tab.sum)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="mt-2 flex items-center gap-2 text-xs text-muted" role="status">
        <Check size={13} className="text-pos" />
        <span className="num">
          The cells add up to {isPnl ? money(tab.sum, { signed: true }) : money(tab.sum)}; the {isPnl ? "run's total change" : "book's total value"} is{" "}
          {isPnl ? money(tab.total, { signed: true }) : money(tab.total)} (difference {tab.residual.toFixed(2)}).
        </span>
      </p>
    </figure>
  );
}

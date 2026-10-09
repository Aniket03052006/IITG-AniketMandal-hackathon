import type { LabCell } from "../../api/types";

const pp = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(2)} pp`;
const shade = (v: number, reach: number) => `color-mix(in oklab, var(${v >= 0 ? "--color-pos" : "--color-neg"}) ${Math.round(Math.min(1, Math.abs(v) / reach) * 38)}%, var(--color-paper-2))`;

/** A grid of what-if runs of the baseline. Every cell prints its numbers; the shade only repeats the sign. A cell is not "good" because it is the largest. */
export function SensitivityGrid({ title, rowLabel, colLabel, rows, cols, cell, reach, shipped }: {
  title: string;
  rowLabel: string;
  colLabel: string;
  rows: { key: string; label: string }[];
  cols: { key: string; label: string }[];
  cell: (r: string, c: string) => LabCell | undefined;
  reach: number;
  shipped: (c: LabCell) => boolean;
}) {
  return (
    <div className="scroll-x">
      <table className="dtable rb-grid-table">
        <caption className="mb-1 text-left text-sm font-medium">{title}</caption>
        <thead>
          <tr>
            <th scope="col"><span className="sr-only">{rowLabel} by {colLabel}</span></th>
            {cols.map((c) => <th key={c.key} scope="col" className="text-right">{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              {cols.map((c) => {
                const x = cell(r.key, c.key);
                if (!x) return <td key={c.key} />;
                return (
                  <td key={c.key} className="text-right" style={{ background: shade(x.active_return, reach) }} data-shipped={shipped(x)}>
                    <span className="num block">{pp(x.active_return)}</span>
                    <span className="num block text-xs text-muted">placebo {Math.round(x.placebo_percentile * 100)}th{shipped(x) ? " · shipped" : ""}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

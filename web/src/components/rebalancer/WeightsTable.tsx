import clsx from "clsx";
import { useMemo, useState } from "react";
import type { RebalanceCycleDetail, RebalanceName } from "../../api/types";
import { pp, REASON_HELP, REASON_LABEL, share, type SeriesSpec } from "../../lib/rebalancer";

type SortKey = "weight" | "active" | "score" | "ticker";

const SORTS: [SortKey, string][] = [["weight", "Weight"], ["active", "Active vs benchmark"], ["score", "Sentiment score"], ["ticker", "Ticker"]];

/** Every stock at the selected cycle: the exact figures the chart draws, and the named reason each one holds its weight. */
export function WeightsTable({ detail, series, focus, onHover, onSelect }: {
  detail: RebalanceCycleDetail;
  series: SeriesSpec[];
  /** the stock highlighted in the chart (hovered, else selected) */
  focus: string | null;
  onHover: (t: string | null) => void;
  onSelect: (t: string) => void;
}) {
  const [sort, setSort] = useState<SortKey>("weight");
  const by = useMemo(() => new Map(series.map((s) => [s.ticker, s])), [series]);
  const rows = useMemo(() => {
    const r = [...detail.names];
    const key: Record<SortKey, (n: RebalanceName) => number | string> = { weight: (n) => -n.weight, active: (n) => -Math.abs(n.active), score: (n) => -n.score, ticker: (n) => n.ticker };
    return r.sort((a, b) => (key[sort](a) < key[sort](b) ? -1 : key[sort](a) > key[sort](b) ? 1 : a.ticker.localeCompare(b.ticker)));
  }, [detail.names, sort]);
  const reach = Math.max(0.005, ...detail.names.map((n) => Math.abs(n.active)));

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor="rb-sort" className="text-sm text-muted">Sort by</label>
        <select id="rb-sort" className="field w-auto" value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          {SORTS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </div>
      <div className="scroll-x">
        <table className="dtable min-w-[46rem]">
          <caption className="sr-only">Weight of every stock in the index at the selected cycle, against its equal-weight benchmark</caption>
          <thead>
            <tr>
              <th scope="col">Stock</th>
              <th scope="col" className="text-right">Weight</th>
              <th scope="col" className="text-right">Benchmark</th>
              <th scope="col">Active</th>
              <th scope="col" className="text-right">Change</th>
              <th scope="col" className="text-right">Sentiment</th>
              <th scope="col" className="text-right">Reports</th>
              <th scope="col">Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((n) => {
              const s = by.get(n.ticker);
              const pos = n.active > 0;
              return (
                <tr key={n.ticker} className={clsx("rb-row", focus === n.ticker && "rb-row-on")} onMouseEnter={() => onHover(n.ticker)} onMouseLeave={() => onHover(null)}>
                  <th scope="row">
                    <button type="button" className="rb-stock" aria-pressed={focus === n.ticker} onClick={() => onSelect(n.ticker)}>
                      <i className="rb-swatch" style={{ background: s?.stroke ?? "var(--color-muted)" }} aria-hidden="true" />
                      <b className="num">{n.ticker}</b>
                      <span className="rb-name">{s?.name ?? ""}</span>
                    </button>
                  </th>
                  <td className="num text-right">{share(n.weight)}</td>
                  <td className="num text-right text-muted">{share(s?.benchmark ?? 0)}</td>
                  <td>
                    <span className="rb-active" role="img" aria-label={`${pp(n.active)} against the benchmark`}>
                      <span className="rb-active-track">
                        <span className={clsx("rb-active-fill", pos ? "rb-pos" : "rb-neg")} style={pos ? { left: "50%", width: `${(n.active / reach) * 50}%` } : { right: "50%", width: `${(-n.active / reach) * 50}%` }} />
                      </span>
                      <span className={clsx("num rb-active-n", n.active > 5e-4 ? "text-pos" : n.active < -5e-4 ? "text-neg" : "text-muted")}>{pp(n.active)}</span>
                    </span>
                  </td>
                  <td className={clsx("num text-right", n.change > 5e-5 ? "text-pos" : n.change < -5e-5 ? "text-neg" : "text-muted")}>{Math.abs(n.change) > 5e-5 ? pp(n.change) : "–"}</td>
                  <td className="num text-right">{n.score > 0 ? "+" : n.score < 0 ? "−" : ""}{Math.abs(n.score).toFixed(2)}</td>
                  <td className="num text-right text-muted">{n.reports}</td>
                  <td><span className="tag" title={REASON_HELP[n.reason]}>{REASON_LABEL[n.reason]}</span></td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">Index</th>
              <td className="num text-right">{share(detail.names.reduce((a, n) => a + n.weight, 0))}</td>
              <td className="num text-right text-muted">{share(series.reduce((a, s) => a + s.benchmark, 0))}</td>
              <td className="num text-muted">{pp(detail.names.reduce((a, n) => a + n.active, 0))}</td>
              <td colSpan={4} />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

import { useState } from "react";
import { useAttribution } from "../../api/hooks";
import type { AttributionRow, AttributionTable, StressAttribution } from "../../api/types";
import { money, pct } from "../../lib/format";
import { DIMENSION_ORDER } from "../../lib/propagation";
import { Waterfall } from "../portfolio/Waterfall";
import { KindBadge } from "../ProvenanceKind";
import { Tabs } from "../Tabs";
import { Heatmap } from "../portfolio/Heatmap";
import { Check } from "../icons";

function Bars({ t }: { t: AttributionTable }) {
  const rows: AttributionRow[] = t.rows;
  const max = Math.max(...rows.map((r) => Math.abs(r.delta)), 1);
  return (
    <ul className="grid gap-2" aria-label={t.label}>
      {rows.slice(0, 12).map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_5.5rem_3.5rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-2" title={r.label}>{r.label}</span>
          <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
            <span className={r.delta < 0 ? "block h-full rounded-sm bg-neg" : "block h-full rounded-sm bg-pos"} style={{ width: `${Math.max(2, (Math.abs(r.delta) / max) * 100)}%` }} />
          </span>
          <span className="num text-right">{money(r.delta, { signed: true })}</span>
          <span className="num text-right text-xs text-muted">{r.share_of_total != null ? pct(r.share_of_total, 0) : "–"}</span>
        </li>
      ))}
      {rows.length > 12 && <li className="text-xs text-muted">The 12 largest of {rows.length}; the rest are in the sum below.</li>}
    </ul>
  );
}

/** Why did the portfolio move? One total, regrouped: every table adds up to it (and says so). A sensitivity decomposition under the scenario's assumptions. */
export function AttributionPanel({ att }: { att: StressAttribution }) {
  const tables = [att.drivers, ...att.tables].sort((a, b) => DIMENSION_ORDER.indexOf(a.dimension) - DIMENSION_ORDER.indexOf(b.dimension));
  const [dim, setDim] = useState(tables[0]?.dimension ?? "driver");
  const t = tables.find((x) => x.dimension === dim) ?? tables[0]!;
  return (
    <section className="mt-6 border-t border-rule pt-5" aria-label="Why the portfolio moved">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Why the portfolio moved</p>
        <KindBadge kind="scenario" label="Modeled, not causal" />
      </div>
      <p className="mt-2 max-w-[70ch] font-display text-lg font-semibold">{att.headline}</p>
      {att.drivers.rows.length > 0 && (
        <div className="mt-4 max-w-[40rem]">
          <Waterfall rows={att.drivers.rows.map((r) => ({ key: r.key, label: r.label, baseline_value: r.baseline_value, delta: r.delta, share_of_loss: r.share_of_total ?? null }))} total={att.total_pnl} />
        </div>
      )}
      <div className="mt-4">
        <Tabs tabs={tables.map((x) => ({ id: x.dimension, label: x.label.replace(/^By /, "").replace(/^./, (c) => c.toUpperCase()) }))} active={t.dimension} onChange={setDim} label="Attribution by">
          <div role="presentation" className="mt-3 max-w-[56rem]">
            <Bars t={t} />
            <p className="mt-3 flex items-center gap-2 text-xs text-muted" role="status">
              <Check size={13} className="text-pos" />
              <span className="num">
                The rows add up to {money(t.sum, { signed: true })}; the run's total change is {money(t.total, { signed: true })} (difference {t.residual.toFixed(2)}).
              </span>
            </p>
          </div>
        </Tabs>
      </div>
      {att.matrix && (
        <div className="mt-6">
          <Heatmap tab={att.matrix} title="Where each shock landed: sector by market factor" unitLabel="modeled change; the darkest cells are the largest" />
        </div>
      )}
      <p className="mt-3 max-w-[70ch] text-xs text-muted">{att.note} {att.labels.join(" ")}</p>
    </section>
  );
}

/** The attribution of any completed run (the catalog scenario on the Stress page). Hidden when the server cannot attribute it. */
export function RunAttribution({ runId, enabled = true }: { runId: string; enabled?: boolean }) {
  const q = useAttribution(runId, enabled);
  if (!enabled || !q.data) return null;
  return <AttributionPanel att={q.data} />;
}

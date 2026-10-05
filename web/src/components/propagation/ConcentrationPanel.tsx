import { useState } from "react";
import type { ConcentrationView, DimensionConcentration, OverlapView } from "../../api/types";
import { money, pct } from "../../lib/format";
import { StateNotice } from "../StateNotice";
import { Tabs } from "../Tabs";
import { AdjustedChip } from "./AdjustedChip";
import { BasisChip } from "./StatusChip";

function Dim({ d }: { d: DimensionConcentration }) {
  const max = Math.max(...d.rows.map((r) => r.share), 0.0001);
  return (
    <div>
      <ul className="grid gap-2" aria-label={d.label}>
        {d.rows.slice(0, 8).map((r) => (
          <li key={r.key} className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_3.5rem_auto] items-center gap-3 text-sm">
            <span className="truncate text-ink-2" title={r.label}>{r.label}</span>
            <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
              <span className={r.flagged ? "block h-full rounded-sm bg-warn" : "block h-full rounded-sm bg-faint"} style={{ width: `${(r.share / max) * 100}%` }} />
            </span>
            <span className="num text-right">{pct(r.share, 1)}</span>
            <span className="text-xs">{r.flagged ? <span className="font-medium text-warn">flagged</span> : <span className="num text-muted">{money(r.value)}</span>}</span>
          </li>
        ))}
        {d.rows.length > 8 && <li className="text-xs text-muted">The 8 largest of {d.rows.length}.</li>}
      </ul>
      <p className="mt-2 text-xs text-muted">
        {d.hhi > 0 && <span className="num">Herfindahl {d.hhi.toFixed(2)} · effective items {d.effective_n.toFixed(1)} of {d.item_count}. </span>}
        {d.reason ?? ""} {d.note ?? ""}
      </p>
    </div>
  );
}

/** Where is the portfolio concentrated? Only meaningful concentration is flagged, and several events on the same risk factor and holdings are shown as one concentrated risk. */
export function ConcentrationPanel({ view, overlaps, heading = "Concentration and blind spots" }: { view?: ConcentrationView; overlaps?: OverlapView; heading?: string }) {
  const [dim, setDim] = useState("sector");
  const d = view?.dimensions.find((x) => x.dimension === dim) ?? view?.dimensions[0];
  return (
    <section className="mt-6 border-t border-rule pt-5" aria-label={heading}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">{heading}</p>
        <AdjustedChip notice={view?.adjustments ?? overlaps?.adjustments} />
      </div>
      {view && (
        <>
          {view.flags.length > 0 ? (
            <ul className="mt-3 max-w-[70ch] list-disc space-y-1 pl-5 text-sm text-ink-2" aria-label="Meaningful concentration">
              {view.flags.map((f) => <li key={f}>{f}</li>)}
            </ul>
          ) : (
            <p className="mt-3 max-w-[70ch] text-sm text-ink-2">No dimension of this portfolio is concentrated by the test below.</p>
          )}
          {d && (
            <div className="mt-4">
              <Tabs tabs={view.dimensions.map((x) => ({ id: x.dimension, label: x.label }))} active={d.dimension} onChange={setDim} label="Concentration by">
                <div role="presentation" className="mt-3 max-w-[56rem]"><Dim d={d} /></div>
              </Tabs>
            </div>
          )}
          <p className="mt-3 max-w-[70ch] text-xs text-muted">{view.note}</p>
        </>
      )}
      {overlaps && (
        <div className="mt-6" aria-label="Overlapping events">
          <p className="text-sm font-semibold">Overlapping events</p>
          {overlaps.clusters.length === 0 ? (
            <p className="mt-1 max-w-[70ch] text-sm text-muted">{overlaps.reason ?? "No overlapping events."} {overlaps.note}</p>
          ) : (
            <ul className="mt-3 grid max-w-[60rem] gap-4">
              {overlaps.clusters.map((c) => (
                <li key={c.risk_factor} className="rounded-md border border-warn bg-warn-dim p-4">
                  <StateNotice tone="warn" what={`Concentrated risk: ${c.risk_factor_label}`} why={c.sentence} />
                  <ol className="mt-3 grid gap-1 text-sm" aria-label="Events on the same risk factor">
                    {c.events.map((e) => (
                      <li key={e.event_id}><span className="text-xs text-muted">{e.materiality.toLowerCase()} · </span>{e.headline}</li>
                    ))}
                  </ol>
                  <p className="mt-3 text-xs text-muted">↓ the same risk factor ↓ the same holdings ({pct(c.shared_share)} of the book, {money(c.shared_value)})</p>
                  <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
                    {c.shared_holdings.slice(0, 8).map((h) => (
                      <li key={h.asset_id}>{h.name} <BasisChip basis={h.basis} /></li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

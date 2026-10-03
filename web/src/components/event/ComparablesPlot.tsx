import type { ImpactAssessment } from "../../api/types";
import { pct, sigma } from "../../lib/format";
import { KindBadge } from "../ProvenanceKind";

/**
 * What comparable past events actually realised, as one picture: the 10th-90th percentile band and median of realised severity (sigma) for
 * the events the model scored in the same bucket, the model's own estimate against it, and the 3σ "extreme" line. Aggregates of the
 * model's out-of-fold history: they are statistics of a bucket, not a list of individual events.
 */
export function ComparablesPlot({ impact, baseRate }: { impact: ImpactAssessment; baseRate?: number }) {
  const { realised_severity_low: lo, realised_severity_median: mid, realised_severity_high: hi, predicted_severity: pred, comparable_events: n, p_extreme: pe } = impact;
  if (lo == null || mid == null || hi == null || n == null) return null;
  const xmax = Math.max(4, Math.ceil(Math.max(hi * 1.1, (pred ?? 0) * 1.25)));
  const at = (v: number) => `${Math.min(100, Math.max(0, (v / xmax) * 100))}%`;
  const ticks = Array.from({ length: xmax + 1 }, (_, i) => i);
  const aria = `Comparable events realised ${sigma(lo)} to ${sigma(hi)}, median ${sigma(mid)}${pred != null ? `; the model estimates ${sigma(pred)}` : ""}`;
  const bars: { name: string; v: number; strong: boolean }[] = [];
  if (pe != null) bars.push({ name: `These ${n.toLocaleString("en-US")} comparable events`, v: pe, strong: true });
  if (baseRate != null) bars.push({ name: "All events the model has seen", v: baseRate, strong: false });
  const bmax = Math.max(0.0001, ...bars.map((b) => b.v));
  return (
    <div className="plot">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">Comparable historical events</h3>
        <KindBadge kind="historical" />
      </div>
      <p className="mb-5 max-w-[66ch] text-sm text-muted">
        {n.toLocaleString("en-US")} past ticker-sessions that the model scored the same. This is an aggregate of the model's own history, not a list of individual events.
      </p>
      <div className="plot-axis" role="img" aria-label={aria}>
        <div className="plot-line" />
        {ticks.map((t) => (
          <span key={t} className="plot-tick" style={{ left: at(t) }}>
            <i />
            <b className="num">{t}σ</b>
          </span>
        ))}
        <span className="plot-extreme" style={{ left: at(3) }}>
          <b>extreme (score 7+)</b>
        </span>
        <span className="plot-band" style={{ left: at(lo), width: `calc(${at(hi)} - ${at(lo)})` }} />
        <span className="plot-median" style={{ left: at(mid) }} />
        {pred != null && (
          <span className="plot-pred" style={{ left: at(pred) }}>
            <i />
          </span>
        )}
      </div>
      <ul className="plot-legend">
        <li>
          <span className="sw sw-band" /> Realised severity of comparable events: 10th to 90th percentile <span className="num">({sigma(lo)} to {sigma(hi)})</span>, median <span className="num">{sigma(mid)}</span>
        </li>
        {pred != null && (
          <li>
            <span className="sw sw-pred" /> The model's estimate for this report <span className="num">({sigma(pred)})</span>
          </li>
        )}
      </ul>
      {bars.length > 0 && (
        <div className="mt-6">
          <p className="mb-2 text-sm font-medium">Share that realised a move of 3σ or more</p>
          <ul className="space-y-2">
            {bars.map((b) => (
              <li key={b.name} className="grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)_3.5rem] items-center gap-3 text-sm">
                <span className="text-ink-2">{b.name}</span>
                <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
                  <span className={b.strong ? "block h-full rounded-sm bg-sev-high bar-grow" : "block h-full rounded-sm bg-faint bar-grow"} style={{ width: `${(b.v / bmax) * 100}%` }} />
                </span>
                <span className="num text-right">{pct(b.v, 1)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

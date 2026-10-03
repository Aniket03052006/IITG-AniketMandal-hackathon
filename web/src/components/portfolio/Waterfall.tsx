import type { Contribution } from "../../api/types";
import { ASSET_CLASS_LABEL, money } from "../../lib/format";

/**
 * The change as a waterfall: each asset class steps the running total down (or up) to the scenario's total change. Drawn from zero, not from
 * the portfolio's value, because the change is small beside the book and would vanish on that axis. Sensitivity to the scenario's shocks, not
 * a causal attribution of the event.
 */
export function Waterfall({ rows, total }: { rows: Contribution[]; total: number }) {
  const items = [...rows].filter((r) => Math.abs(r.delta) > 0.5 || rows.length <= 4).sort((a, b) => a.delta - b.delta);
  if (items.length === 0) return <p className="text-sm text-muted">No holding changed in value under this scenario.</p>;
  const W = 640;
  const H = 230;
  const padL = 12;
  const padR = 12;
  const top = 34;
  const bottom = 56;
  const n = items.length + 1;
  const colW = (W - padL - padR) / n;
  const barW = Math.min(64, colW * 0.62);
  let run = 0;
  const steps = items.map((it) => {
    const from = run;
    run += it.delta;
    return { it, from, to: run };
  });
  const lo = Math.min(0, run, ...steps.map((s) => Math.min(s.from, s.to)));
  const hi = Math.max(0, ...steps.map((s) => Math.max(s.from, s.to)));
  const span = hi - lo || 1;
  const y = (v: number) => top + ((hi - v) / span) * (H - top - bottom);
  const label = (k: string, fallback: string) => ASSET_CLASS_LABEL[k] ?? fallback;
  const desc = `Change by asset class: ${steps.map((s) => `${label(s.it.key, s.it.label)} ${money(s.it.delta, { signed: true })}`).join(", ")}; total ${money(total, { signed: true })}`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="wf" role="img" aria-label={desc}>
      <line x1={padL} x2={W - padR} y1={y(0)} y2={y(0)} className="wf-zero" />
      {steps.map((s, i) => {
        const cx = padL + colW * i + colW / 2;
        const y1 = y(Math.max(s.from, s.to));
        const y2 = y(Math.min(s.from, s.to));
        const h = Math.max(2, y2 - y1);
        return (
          <g key={s.it.key} className="wf-col" style={{ ["--i" as string]: i }}>
            {i > 0 && <line x1={cx - colW} x2={cx - barW / 2} y1={y(s.from)} y2={y(s.from)} className="wf-link" />}
            <rect x={cx - barW / 2} y={y1} width={barW} height={h} rx={2} className={s.it.delta < 0 ? "wf-neg" : "wf-pos"} />
            <text x={cx} y={y1 - 6} textAnchor="middle" className="wf-val">
              {money(s.it.delta, { signed: true })}
            </text>
            <text x={cx} y={H - 30} textAnchor="middle" className="wf-name">
              {label(s.it.key, s.it.label)}
            </text>
          </g>
        );
      })}
      {(() => {
        const i = items.length;
        const cx = padL + colW * i + colW / 2;
        const y1 = y(Math.max(0, total));
        const y2 = y(Math.min(0, total));
        return (
          <g className="wf-col" style={{ ["--i" as string]: i }}>
            <line x1={cx - colW} x2={cx - barW / 2} y1={y(run)} y2={y(run)} className="wf-link" />
            <rect x={cx - barW / 2} y={y1} width={barW} height={Math.max(2, y2 - y1)} rx={2} className="wf-total" />
            <text x={cx} y={y1 - 6} textAnchor="middle" className="wf-val wf-val-total">
              {money(total, { signed: true })}
            </text>
            <text x={cx} y={H - 30} textAnchor="middle" className="wf-name wf-name-total">
              Total change
            </text>
          </g>
        );
      })()}
    </svg>
  );
}

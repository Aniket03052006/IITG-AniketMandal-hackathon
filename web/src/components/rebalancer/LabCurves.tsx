import { useState } from "react";
import type { LabStrategy } from "../../api/types";
import { linePath, spreadLabels } from "../../lib/rebalancer";

const W = 760;
const H = 300;
const PAD = { l: 52, r: 150, t: 12, b: 26 };
/** Strategy -> a token and a dash pattern: colour never carries the identity alone (every line is also labelled at its end). */
export const LAB_STYLE: Record<string, { stroke: string; dash?: string; width: number }> = {
  sentiment: { stroke: "var(--color-accent)", width: 2.8 },
  sentiment_risk: { stroke: "var(--color-sector-energy)", dash: "7 4", width: 2 },
  sentiment_impact: { stroke: "var(--color-sector-healthcare)", dash: "2 3", width: 2 },
  equal_weight: { stroke: "var(--color-ink-2)", width: 1.6 },
  buy_and_hold: { stroke: "var(--color-muted)", dash: "1 4", width: 2 },
};
const pct = (v: number, d = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(d)}%`;

/** Every strategy's cumulative net return (or its drawdown) over the same sessions, labelled at the line's end. */
export function LabCurves({ strategies, dates }: { strategies: LabStrategy[]; dates: string[] }) {
  const [mode, setMode] = useState<"cumulative" | "drawdown">("cumulative");
  const series = strategies.map((s) => ({ s, v: mode === "cumulative" ? s.cumulative : s.drawdown }));
  const all = [0, ...series.flatMap((x) => x.v)];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = Math.max(hi - lo, 0.002);
  const xs = dates.map((_, i) => PAD.l + (i / Math.max(1, dates.length - 1)) * (W - PAD.l - PAD.r));
  const y = (v: number) => PAD.t + (1 - (v - lo) / span) * (H - PAD.t - PAD.b);
  const ends = spreadLabels(series.map((x) => y(x.v[x.v.length - 1]!)), 14, PAD.t + 6, H - PAD.b);
  const summary = series.map((x) => `${x.s.label} ${pct(x.v[x.v.length - 1]!)}`).join("; ");
  return (
    <figure className="m-0">
      <div role="group" aria-label="Curve" className="mb-2 flex gap-2">
        <button type="button" className="chip" aria-pressed={mode === "cumulative"} onClick={() => setMode("cumulative")}>Cumulative return</button>
        <button type="button" className="chip" aria-pressed={mode === "drawdown"} onClick={() => setMode("drawdown")}>Drawdown</button>
      </div>
      <div className="scroll-x">
        <svg viewBox={`0 0 ${W} ${H}`} className="rb-curve min-w-[40rem]" role="img" aria-label={`${mode === "cumulative" ? "Cumulative net return" : "Drawdown from the previous peak"} of ${series.length} strategies over ${dates.length} sessions, ending at: ${summary}.`}>
          <line x1={PAD.l} x2={W - PAD.r} y1={y(0)} y2={y(0)} className="rb-zero" />
          {[hi, lo].map((v) => <text key={v} x={PAD.l - 6} y={y(v) + 3.5} textAnchor="end" className="rb-tick">{pct(v)}</text>)}
          {series.map(({ s, v }) => {
            const st = LAB_STYLE[s.id] ?? { stroke: "var(--color-muted)", width: 1.5 };
            return <path key={s.id} d={linePath(xs, v, y)} fill="none" stroke={st.stroke} strokeWidth={st.width} strokeDasharray={st.dash} strokeLinejoin="round" data-strategy={s.id} />;
          })}
          {series.map(({ s, v }, k) => (
            <text key={s.id} x={W - PAD.r + 8} y={ends[k]! + 3.5} className="rb-ticker">
              {s.label.replace(/ \(.*\)$/, "")} {pct(v[v.length - 1]!)}
            </text>
          ))}
          <text x={PAD.l} y={H - 8} className="rb-tick">{dates[0]}</text>
          <text x={W - PAD.r} y={H - 8} textAnchor="end" className="rb-tick">{dates[dates.length - 1]}</text>
        </svg>
      </div>
    </figure>
  );
}

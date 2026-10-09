import type { RebalancerOverview, RebalancerParams } from "../../api/types";

export interface WhatIfValues {
  tilt: number | null;
  half_life_hours: number | null;
  max_turnover: number | null;
}

interface SliderProps { id: string; label: string; hint: string; value: number; min: number; max: number; step: number; unit: string; shipped: number; set: (n: number) => void }

/** Module-level on purpose: a component defined inside another remounts on every render and would drop the slider being dragged. */
function Row({ id, label, hint, value, min, max, step, unit, shipped, set }: SliderProps) {
  return (
    <div className="grid gap-1">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-sm font-medium">{label}</label>
        <output htmlFor={id} className="num text-sm">{unit === "%" ? (value * 100).toFixed(1) : value}{unit}</output>
      </div>
      <input id={id} type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} aria-describedby={`${id}-hint`} />
      <p id={`${id}-hint`} className="text-xs text-muted">{hint} Shipped: <span className="num">{unit === "%" ? (shipped * 100).toFixed(1) : shipped}{unit}</span>.</p>
    </div>
  );
}

/** Three sliders that change the rule for this view only. The shipped parameters are never modified, and the page says so whenever they differ. */
export function WhatIf({ overview, params, onChange, onReset }: {
  overview: RebalancerOverview;
  params: RebalancerParams;
  onChange: (v: Partial<WhatIfValues>) => void;
  onReset: () => void;
}) {
  const d = overview.params;
  return (
    <div>
      <div className="grid gap-5 sm:grid-cols-3">
        <Row id="rb-tilt" label="Tilt strength" hint="How hard a score moves a weight. 0 holds the benchmark." value={params.tilt} min={0} max={overview.tilt_max} step={0.1} unit="" shipped={d.tilt} set={(n) => onChange({ tilt: n })} />
        <Row id="rb-hl" label="Half-life" hint="Hours for a report's weight to halve." value={params.half_life_hours} min={1} max={240} step={1} unit=" h" shipped={d.half_life_hours} set={(n) => onChange({ half_life_hours: n })} />
        <Row id="rb-to" label="Turnover cap per cycle" hint="The most of the index traded in one cycle." value={params.max_turnover} min={0.005} max={overview.max_turnover_limit} step={0.005} unit="%" shipped={d.max_turnover} set={(n) => onChange({ max_turnover: n })} />
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-sm" onClick={onReset} disabled={params.is_default}>Reset to the shipped parameters</button>
        <span className="text-xs text-muted">{params.is_default ? "Showing the index of record." : "What-if: these parameters apply to this view only; the server's configuration is unchanged."}</span>
      </div>
    </div>
  );
}

import clsx from "clsx";
import type { StressResult } from "../../api/types";
import { money, pct } from "../../lib/format";
import { useTween } from "../../lib/motion";
import { KindBadge } from "../ProvenanceKind";

function Figure({ label, r, tone }: { label: string; r?: StressResult; tone: "base" | "scenario" }) {
  const sum = r?.summary;
  const v = useTween(sum?.pnl ?? 0);
  return (
    <div className={clsx("wi-fig", tone === "scenario" && "wi-fig-scenario")}>
      <p className="eyebrow">{label}</p>
      {sum ? (
        <>
          <p className={clsx("num text-3xl font-medium", sum.pnl < 0 ? "text-neg" : "text-pos")}>{money(v, { signed: true })}</p>
          <p className="num text-sm text-muted">
            {pct(sum.pnl_pct, 2, true)} · severity ×{r!.severity?.scale.toFixed(2)}
          </p>
        </>
      ) : (
        <p className="mt-1 text-sm text-muted">Computing…</p>
      )}
    </div>
  );
}

/**
 * Test a different severity. The slider changes only the scenario's scale; the same deterministic engine recomputes the book. Always labelled a
 * simulation: nothing here is a model prediction.
 */
export function WhatIf({
  eventImpact,
  severity,
  onSeverity,
  base,
  scenario,
  pending,
  onShowMath,
}: {
  eventImpact: number;
  severity: number;
  onSeverity: (v: number) => void;
  base?: StressResult;
  scenario?: StressResult;
  pending: boolean;
  onShowMath: () => void;
}) {
  const same = severity === eventImpact;
  return (
    <section className="whatif" aria-labelledby="whatif-h">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="whatif-h" className="text-lg font-semibold">
          Test a different severity
        </h3>
        <KindBadge kind="scenario" label="Scenario simulation, not a prediction" />
      </div>
      <p className="mb-4 max-w-[64ch] text-sm text-muted">
        Slide the impact score to see how the same scenario would hit the book if the event were milder or more severe. The engine recomputes every position.
      </p>
      <div className="wi-slider">
        <label htmlFor="whatif-range" className="flex items-baseline justify-between gap-3 text-sm">
          <span className="text-ink-2">Impact score applied</span>
          <span className="num text-xl font-medium">{severity.toFixed(1)}</span>
        </label>
        <input id="whatif-range" type="range" min={1} max={10} step={0.5} value={severity} onChange={(e) => onSeverity(Number(e.target.value))} aria-valuetext={`impact ${severity.toFixed(1)} of 10`} />
        <div className="flex justify-between text-2xs text-muted" aria-hidden="true">
          <span>1 mild</span>
          <span>event's own: {eventImpact}</span>
          <span>10 severe</span>
        </div>
      </div>
      <div className="wi-compare" aria-live="polite" aria-busy={pending}>
        <Figure label={`Base · the event's own impact (${eventImpact})`} r={base} tone="base" />
        <Figure label={same ? "Scenario · same as base" : `Scenario · impact ${severity.toFixed(1)}`} r={same ? base : scenario} tone="scenario" />
      </div>
      <p className="mt-3 text-sm text-muted">
        Severity scales every shock by a clamped ratio of the impact to a reference, so very mild or very severe scores saturate.{" "}
        <button type="button" className="text-accent underline underline-offset-2" onClick={onShowMath}>
          How is this calculated?
        </button>
      </p>
    </section>
  );
}

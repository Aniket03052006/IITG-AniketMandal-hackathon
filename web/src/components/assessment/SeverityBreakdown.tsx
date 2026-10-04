import clsx from "clsx";
import type { RiskAssessment, SeverityAssessment } from "../../api/types";
import { AssessmentKind } from "./AssessmentKind";
import { StateNotice } from "../StateNotice";

const ARROW: Record<string, string> = { UP: "↑", DOWN: "↓", NEUTRAL: "→" };
const WORD: Record<string, string> = { UP: "raises severity", DOWN: "lowers severity", NEUTRAL: "near the middle" };

/** The real risk drivers: each is one factor's computed value turned into a sentence by rule. Arrow + word + number, never colour alone. */
export function RiskDrivers({ sev }: { sev: SeverityAssessment }) {
  return (
    <ul className="space-y-2" aria-label="Risk drivers">
      {sev.drivers.map((d) => (
        <li key={d.factor_id} className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-baseline gap-2 text-sm">
          <span aria-hidden="true" className={clsx("num font-semibold", d.direction === "UP" ? "text-sev-high" : d.direction === "DOWN" ? "text-muted" : "text-ink-2")}>
            {ARROW[d.direction]}
          </span>
          <span className="text-ink">
            {d.text} <span className="text-muted">({WORD[d.direction]})</span>
          </span>
          <span className="num text-xs text-muted">+{d.points.toFixed(2)} pts</span>
        </li>
      ))}
    </ul>
  );
}

/** Every factor with its value, weight and points: the whole calculation, nothing hidden. Unavailable factors are listed with the reason, not guessed. */
export function FactorTable({ sev }: { sev: SeverityAssessment }) {
  return (
    <div role="table" aria-label="How the severity score is built">
      <div role="rowgroup">
        {sev.factors.map((f) => (
          <div key={f.id} role="row" className={clsx("factor", !f.available && "factor-off")}>
            <div role="cell" className="min-w-0">
              <p className="text-sm font-medium text-ink">{f.label}</p>
              <p className="mt-0.5 flex flex-wrap items-center gap-1.5">
                <AssessmentKind kind={f.kind} />
              </p>
            </div>
            <div role="cell" className="num text-sm text-ink-2">
              {f.available && f.value != null ? (
                <>
                  <span className="factor-bar block" aria-hidden="true">
                    <i style={{ width: `${Math.round(f.value * 100)}%` }} />
                  </span>
                  <span className="sr-only">value </span>
                  {f.value.toFixed(2)} <span className="text-muted">× {f.weight.toFixed(2)}</span>
                </>
              ) : (
                <>
                  <span className="factor-bar block" aria-hidden="true" />
                  <span className="text-muted">left out</span>
                </>
              )}
            </div>
            <div role="cell" className="min-w-0 text-xs text-muted">
              {f.detail}
            </div>
            <div role="cell" className="num text-sm font-medium text-ink sm:text-right">
              {f.available ? `+${f.contribution_points.toFixed(2)}` : "—"}
              <span className="sr-only"> points</span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Weights shown are after renormalising over the factors that were available (configured weights: {sev.factors.map((f) => `${f.label.toLowerCase()} ${f.raw_weight}`).join(", ")}).
      </p>
    </div>
  );
}

/** The severity chapter's body: drivers, the full table, the sensitivity range and the caveats. */
export function SeverityBreakdown({ a }: { a: RiskAssessment }) {
  const sev = a.severity;
  if (!sev) return null;
  return (
    <div className="space-y-8">
      <div className="impact-grid">
        <div>
          <h3 className="text-sm font-semibold">What drives the score</h3>
          <p className="mb-3 mt-0.5 text-xs text-muted">Each line is a factor's computed value for this report, in words. The points add up to the score.</p>
          <RiskDrivers sev={sev} />
          {sev.omitted.length > 0 && (
            <div className="mt-5">
              <p className="eyebrow">Left out, not guessed</p>
              <ul className="mt-1 space-y-1 text-sm text-muted">
                {sev.omitted.map((o) => (
                  <li key={o.id}>
                    <span className="font-medium text-ink-2">{o.label}:</span> {o.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="space-y-5">
          <div className="fact">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="eyebrow">Severity score</p>
              <AssessmentKind kind="JUDGEMENT_PRIOR" />
            </div>
            <p className="fact-value num">
              {sev.points.toFixed(1)} <span className="text-base text-muted">→ {sev.score} / 10</span>
            </p>
            <p className="mt-0.5 text-sm text-muted">Rounded to a whole number for the trigger. A triage level, not a forecast.</p>
          </div>
          <div className="fact">
            <p className="eyebrow">If the weights were different</p>
            <p className="fact-value num">
              {sev.low}–{sev.high}
            </p>
            <p className="mt-0.5 text-sm text-muted">{sev.range_basis}</p>
          </div>
          <div className="fact">
            <p className="eyebrow">Uncertainty</p>
            <p className="mt-1 text-sm text-ink-2">
              {sev.uncertainty_stated
                ? `The reading's own uncertainty is ${Math.round(sev.uncertainty * 100)}%`
                : `The reading states no uncertainty (no calibrated confidence), so a neutral ${Math.round(sev.uncertainty * 100)}% is assumed`}
              , which removed {sev.uncertainty_points_removed.toFixed(2)} points. A shakier reading never scores higher.
            </p>
          </div>
        </div>
      </div>
      <details className="disclosure">
        <summary>The full calculation</summary>
        <div className="mt-3 space-y-4">
          <FactorTable sev={sev} />
          <p className="num rounded-md border border-rule bg-paper-2 p-3 text-xs text-ink-2">{sev.formula}</p>
        </div>
      </details>
      {a.conflict && (
        <StateNotice
          tone="warn"
          what="Another report on the same issuer disagrees"
          why={`${a.conflict.note} “${a.conflict.headline}” (${a.conflict.hours_apart} h apart).`}
        />
      )}
    </div>
  );
}

import clsx from "clsx";
import type { ScoreStep } from "../../api/types";
import { pts } from "../../lib/assessment";
import { OriginChip } from "./OriginChip";

/**
 * The score, built line by line: the severity matrix first, then every change on the way to the final number, each tagged with where it comes from.
 * Colour is never the only signal: each row states its direction in words and a signed number.
 */
export function ScoreBuildUp({ steps, score, points }: { steps: ScoreStep[]; score: number; points: number }) {
  const span = Math.max(1, ...steps.slice(1).map((s) => Math.abs(s.effect_points)));
  return (
    <div role="table" aria-label="How the severity score is built">
      <div role="rowgroup">
        {steps.map((s, i) => (
          <div key={s.id} role="row" className="bu-row">
            <div role="cell" className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-ink">
                {s.label} <OriginChip origin={s.origin} />
              </p>
              <p className="mt-0.5 text-sm text-ink-2">{s.value}</p>
            </div>
            <div role="cell" className="min-w-0 text-xs text-muted">
              {s.detail}
            </div>
            <div role="cell" className="num text-sm text-ink sm:text-right">
              {i === 0 ? (
                <>
                  <span className="sr-only">starts at </span>
                  {s.effect_points.toFixed(2)}
                </>
              ) : (
                <>
                  {pts(s.effect_points)}
                  <span className={clsx("bu-bar mt-1", s.effect_points >= 0 ? "bu-pos" : "bu-neg")} aria-hidden="true">
                    <i style={{ left: s.effect_points >= 0 ? "50%" : `${50 - (Math.abs(s.effect_points) / span) * 50}%`, width: `${(Math.abs(s.effect_points) / span) * 50}%` }} />
                  </span>
                </>
              )}
            </div>
            <div role="cell" className="num text-sm text-muted sm:text-right">
              <span className="sr-only">running total </span>
              {s.running.toFixed(2)}
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-sm text-ink">
        <span className="font-medium">Result:</span> <span className="num">{points.toFixed(2)}</span> rounds to <span className="num font-semibold">{score}</span> on the 1 to 10 scale.
      </p>
    </div>
  );
}

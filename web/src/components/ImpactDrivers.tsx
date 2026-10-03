import clsx from "clsx";
import type { ImpactAssessment } from "../api/types";
import { signed } from "../lib/format";

const BASE = "baseline";

/**
 * The per-feature contributions behind an impact estimate, as diverging bars. For the trained model they are the model's own
 * attributions (units in `driver_basis`); for the placeholder rule they are its three hand-set terms. Either way the bars are
 * scaled by the largest contribution on this card, never by a global maximum.
 */
export function ImpactDrivers({ impact }: { impact: ImpactAssessment }) {
  const rows = impact.drivers.filter((d) => d.feature !== BASE);
  const base = impact.drivers.find((d) => d.feature === BASE);
  const maxAbs = Math.max(0.01, ...rows.map((d) => Math.abs(d.contribution)));
  return (
    <>
      {base && (
        <p className="mb-2 text-xs text-muted">
          Starts from <span className="num text-ink-2">{signed(base.contribution, 3)}</span>, {base.note}.
        </p>
      )}
      <ul className="space-y-2">
        {rows.map((d) => (
          <li key={d.feature} className="grid grid-cols-[minmax(0,1fr)_7.5rem_3.25rem] items-center gap-3 sm:grid-cols-[minmax(0,1.3fr)_9rem_3.5rem]">
            <span className="min-w-0 text-sm text-ink-2" title={d.note}>
              <span className="num break-words">{d.feature}</span>
              {(d.note || d.value != null) && (
                <span className="block text-xs text-muted">
                  {d.note}
                  {d.value != null && <span className="num"> · value {Number.isInteger(d.value) ? d.value : d.value.toPrecision(3)}</span>}
                </span>
              )}
            </span>
            <span className="relative h-2 rounded-sm bg-paper-4" aria-hidden="true">
              <span className="absolute inset-y-0 left-1/2 w-px bg-faint" />
              <span
                className={clsx("absolute inset-y-0 rounded-sm", d.contribution >= 0 ? "bg-sev-high" : "bg-sev-low")}
                style={d.contribution >= 0 ? { left: "50%", width: `${(d.contribution / maxAbs) * 50}%` } : { right: "50%", width: `${(Math.abs(d.contribution) / maxAbs) * 50}%` }}
              />
            </span>
            <span className={clsx("num text-right text-sm", d.contribution >= 0 ? "text-sev-high" : "text-sev-low")}>{signed(d.contribution, d.contribution && Math.abs(d.contribution) < 0.01 ? 3 : 2)}</span>
          </li>
        ))}
      </ul>
      {impact.driver_basis && <p className="mt-2 max-w-[70ch] text-xs text-muted">Units: {impact.driver_basis}. Up means a larger expected move; it explains the model, not why the market moves.</p>}
    </>
  );
}

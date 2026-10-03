import clsx from "clsx";
import type { DriverLine } from "../../lib/narrative";
import { signed } from "../../lib/format";

/** Diverging bars of the model's own additive attributions, with plain names. Scaled to the largest on this list, never a global maximum. */
export function DriverBars({ lines, max = 6 }: { lines: DriverLine[]; max?: number }) {
  const shown = lines.slice(0, max);
  const top = Math.max(0.01, ...shown.map((l) => Math.abs(l.contribution)));
  return (
    <ul className="space-y-3" aria-label="Largest contributions to the estimate">
      {shown.map((d) => {
        const up = d.contribution >= 0;
        return (
          <li key={d.feature} className="grid grid-cols-[minmax(0,1fr)_minmax(5rem,9rem)_3.25rem] items-center gap-3">
            <span className="min-w-0 text-sm text-ink-2">{d.label}</span>
            <span className="relative h-2 rounded-sm bg-paper-4" aria-hidden="true">
              <span className="absolute inset-y-0 left-1/2 w-px bg-faint" />
              <span
                className={clsx("absolute inset-y-0 rounded-sm bar-grow", up ? "bg-sev-high" : "bg-sev-low")}
                style={up ? { left: "50%", width: `${(d.contribution / top) * 50}%` } : { right: "50%", width: `${(Math.abs(d.contribution) / top) * 50}%` }}
              />
            </span>
            <span className={clsx("num text-right text-sm", up ? "text-sev-high" : "text-sev-low")}>
              {signed(d.contribution, Math.abs(d.contribution) < 0.01 ? 3 : 2)}
              <span className="sr-only">{up ? " raises the estimate" : " lowers the estimate"}</span>
            </span>
          </li>
        );
      })}
    </ul>
  );
}

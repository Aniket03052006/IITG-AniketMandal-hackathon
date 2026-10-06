import type { MonitorCycle } from "../../api/types";
import { when } from "../../lib/intelligence";

/** The replay clock: the same cycles every run, so the same view is the same for everyone. Cycle 0 is the baseline and reports no changes. */
export function ReplayClock({ cycles, cycle, onChange }: { cycles: MonitorCycle[]; cycle: number; onChange: (c: number) => void }) {
  const last = cycles.length - 1;
  if (last < 1) return null;
  const cur = cycles[cycle];
  return (
    <div className="tl-controls flex flex-wrap items-center gap-3" role="group" aria-label="Replay clock">
      <span className="eyebrow">Replay clock</span>
      <button type="button" className="btn btn-sm" disabled={cycle <= 1} onClick={() => onChange(cycle - 1)} aria-label="Previous cycle">‹</button>
      <input type="range" aria-label="Replay cycle" min={1} max={last} value={Math.max(cycle, 1)} onChange={(e) => onChange(Number(e.target.value))} className="min-w-40 flex-1" />
      <button type="button" className="btn btn-sm" disabled={cycle >= last} onClick={() => onChange(cycle + 1)} aria-label="Next cycle">›</button>
      <output className="num text-sm text-ink-2">Cycle {cycle} of {last}{cur ? ` · ${when(cur.at)}` : ""}</output>
    </div>
  );
}

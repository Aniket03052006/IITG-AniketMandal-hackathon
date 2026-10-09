import type { StrategyInfo } from "../../api/types";
import { StatusTag } from "../ui";

/** Which rule produced the weights. The baseline is the shipped rule; the others are experiments that never replace it. */
export function StrategyPicker({ strategies, value, onChange }: { strategies: StrategyInfo[]; value: string; onChange: (id: string) => void }) {
  const cur = strategies.find((s) => s.id === value);
  return (
    <section aria-label="Strategy" className="card card-pad">
      <div role="radiogroup" aria-label="Strategy" className="flex flex-wrap items-center gap-2">
        {strategies.map((s) => (
          <button key={s.id} type="button" role="radio" aria-checked={value === s.id} className="chip" aria-pressed={value === s.id} disabled={!s.available} title={s.reason ?? s.description} onClick={() => onChange(s.id)}>
            {s.label}
          </button>
        ))}
      </div>
      {cur && (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-2">
          {cur.experimental && <StatusTag tone="warn">Experimental</StatusTag>}
          <span>{cur.description}</span>
        </p>
      )}
      {strategies.some((s) => !s.available) && <p className="mt-1 text-xs text-muted">{strategies.filter((s) => !s.available).map((s) => `${s.label}: ${s.reason}`).join(" · ")}</p>}
    </section>
  );
}

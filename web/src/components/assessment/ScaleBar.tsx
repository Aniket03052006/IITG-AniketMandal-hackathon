import { SCALE_BANDS } from "../../lib/severity";

/** The 1-10 scale as five labelled semantic bands (not quotas), with the score marked in its band. */
export function ScaleBar({ score }: { score: number | null }) {
  return (
    <ol className="scale" aria-label={score === null ? "Severity scale: negligible, low, moderate, high, extreme" : `Severity ${score} of 10 on a scale of negligible, low, moderate, high, extreme`}>
      {SCALE_BANDS.map((b) => {
        const on = score !== null && score >= b.range[0] && score <= b.range[1];
        return (
          <li key={b.id} className="scale-seg" data-band={b.id} data-on={on} data-score={on ? score : undefined} title={`${b.label} (${b.range[0]}-${b.range[1]}): ${b.says}`}>
            <span className="block">{b.label}</span>
            <span className="num block text-2xs text-faint">
              {b.range[0]}–{b.range[1]}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

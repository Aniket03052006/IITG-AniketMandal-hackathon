import clsx from "clsx";
import type { ImpactEstimate } from "../api/types";

const MINUS = "−";
const f = (x: number, d = 3) => `${x < 0 ? MINUS : "+"}${Math.abs(x).toFixed(d)}`;

/** The shared horizontal axis for a column of intervals: always contains zero, symmetric padding, so rows are comparable. */
export function axisFor(rows: ImpactEstimate[], pad = 0.1): [number, number] {
  const lo = Math.min(0, ...rows.map((r) => r.lo ?? r.value ?? 0));
  const hi = Math.max(0, ...rows.map((r) => r.hi ?? r.value ?? 0));
  const span = hi - lo || 1;
  return [lo - span * pad, hi + span * pad];
}

/**
 * A point estimate with its 95% interval on a shared axis, zero marked. The words beside it say what it means
 * (colour is never the only signal): `negativeIsGood` for error differences (negative = the block helps).
 */
export function Interval({
  e,
  axis,
  digits = 3,
  label,
  className,
}: {
  e: ImpactEstimate;
  axis: [number, number];
  digits?: number;
  label?: string;
  className?: string;
}) {
  if (e.value == null) return <span className="text-muted">not evaluable</span>;
  const [min, max] = axis;
  const pos = (x: number) => `${(Math.min(Math.max((x - min) / (max - min), 0), 1) * 100).toFixed(2)}%`;
  const lo = e.lo ?? e.value;
  const hi = e.hi ?? e.value;
  const text = e.lo != null && e.hi != null ? `${f(e.value, digits)}, 95% interval ${f(e.lo, digits)} to ${f(e.hi, digits)}` : f(e.value, digits);
  return (
    <span className={clsx("flex items-center gap-3", className)}>
      <span role="img" aria-label={`${label ?? "estimate"}: ${text}`} className="relative block h-5 w-40 shrink-0 sm:w-52">
        <span className="absolute inset-y-0 w-px bg-rule-strong" style={{ left: pos(0) }} />
        <span className="absolute top-1/2 h-px -translate-y-1/2 bg-ink-2" style={{ left: pos(lo), width: `calc(${pos(hi)} - ${pos(lo)})` }} />
        <span className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-paper bg-ink" style={{ left: pos(e.value) }} />
      </span>
      <span className="num text-xs text-ink-2">
        {f(e.value, digits)}
        {e.lo != null && e.hi != null && (
          <span className="block text-muted">
            {f(e.lo, digits)} to {f(e.hi, digits)}
          </span>
        )}
      </span>
    </span>
  );
}

const VERDICT_STYLE: Record<string, string> = {
  helps: "border-pos text-pos bg-pos-dim",
  hurts: "border-neg text-neg bg-neg-dim",
  "no measurable effect": "border-rule-strong text-ink-2 bg-paper-3",
  "not evaluable": "border-rule text-muted bg-paper-2",
};

/** The verdict is words plus a symbol, never colour alone. */
export function Verdict({ v }: { v: string }) {
  const symbol = v === "helps" ? "▼ " : v === "hurts" ? "▲ " : v === "no measurable effect" ? "= " : "? ";
  return (
    <span className={clsx("inline-block rounded-sm border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap", VERDICT_STYLE[v] ?? VERDICT_STYLE["not evaluable"])}>
      <span aria-hidden="true">{symbol}</span>
      {v}
    </span>
  );
}

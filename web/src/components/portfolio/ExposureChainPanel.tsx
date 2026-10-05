import clsx from "clsx";
import { useExposureChain } from "../../api/hooks";
import type { ChainStep } from "../../api/types";
import { money, pct } from "../../lib/format";
import { KindBadge } from "../ProvenanceKind";
import { Skeleton } from "../ui";

const shock = (s: ChainStep): string => {
  const v = s.applied_shock;
  if (s.unit === "bp") return `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(0)} bp`;
  if (s.unit === "x") return `×${v.toFixed(2)}`;
  return pct(v, 1, true);
};

/**
 * Why did my portfolio move? Event → the shock that applies → the part of your portfolio that takes it → the modeled change. Every line is a
 * regrouping of the finished run's own numbers (see /exposure-chain): nothing is recomputed or written by a model.
 */
export function ExposureChainPanel({ runId, currency }: { runId: string | undefined; currency?: string }) {
  const { data: c, isLoading, error } = useExposureChain(runId);
  if (!runId) return null;
  if (isLoading) return <Skeleton className="h-48 w-full" />;
  if (error || !c) {
    return <p className="text-sm text-muted">The exposure chain is not available for this run{error instanceof Error ? `: ${error.message}` : ""}.</p>;
  }
  const m = (x: number, signed = true) => money(x, { signed, currency });
  return (
    <section aria-label="Why is my portfolio exposed?">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold">Why is my portfolio exposed?</h3>
        <KindBadge kind="scenario" label="Modeled, not a forecast" />
      </div>
      <p className="mb-4 max-w-[68ch] text-ink-2">{c.summary}</p>
      <ol className="chainv">
        <li className="chainv-node">
          <p className="chain-k">Event</p>
          <p className="font-medium text-ink">{c.event_line}</p>
        </li>
        {c.steps.map((s) => (
          <li key={`${s.factor}-${s.scope}`} className="chainv-node">
            <p className="chain-k">
              {s.scope_label} {s.factor_label} <span className="num text-ink">{shock(s)}</span>
            </p>
            <p className="mt-1 text-sm text-ink-2">
              Your exposure: <span className="num font-medium text-ink">{pct(s.exposed_share, 1)}</span> of the portfolio ({s.position_count} position{s.position_count === 1 ? "" : "s"}, {m(s.exposed_value, false)})
            </p>
            <p className="text-xs text-muted">{s.sensitivity}</p>
            <p className={clsx("num mt-1 text-sm font-medium", s.impact < 0 ? "text-neg" : s.impact > 0 ? "text-pos" : "text-ink-2")}>
              Modeled change {m(s.impact)} ({pct(s.impact_pct, 2, true)})
            </p>
          </li>
        ))}
        {c.steps.length === 0 && (
          <li className="chainv-node">
            <p className="chain-k">Your exposure</p>
            <p className="text-ink-2">None of your holdings responds to the shocks that apply.</p>
          </li>
        )}
        <li className="chainv-node">
          <p className="chain-k">Total modeled change</p>
          <p className={clsx("num font-medium", c.total_impact < 0 ? "text-neg" : "text-ink")}>
            {m(c.total_impact)} ({pct(c.total_impact_pct, 2, true)})
          </p>
        </li>
      </ol>
      {c.not_reached && c.not_reached.position_count > 0 && (
        <p className="mt-3 text-sm text-muted">
          Not moved: {pct(c.not_reached.share, 1)} of the portfolio ({c.not_reached.position_count} position{c.not_reached.position_count === 1 ? "" : "s"}) — {c.not_reached.label.toLowerCase()}.
        </p>
      )}
      {c.skipped.length > 0 && (
        <details className="disclosure mt-3">
          <summary>{c.skipped.length} scenario shock{c.skipped.length === 1 ? "" : "s"} did not apply to this event</summary>
          <ul className="mt-2 space-y-1 text-sm text-muted">
            {c.skipped.map((k) => (
              <li key={`${k.factor_label}-${k.scope_label}`}>
                {k.scope_label} {k.factor_label}: {k.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="mt-3 max-w-[68ch] text-xs text-muted">{c.note}</p>
    </section>
  );
}

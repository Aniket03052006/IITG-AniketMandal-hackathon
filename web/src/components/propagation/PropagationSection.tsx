import { Link } from "react-router-dom";
import { useMeta, useOverlaps, usePortfolioStress, usePropagation, useConcentration } from "../../api/hooks";
import { ApiError } from "../../api/client";
import type { AutoStressResult } from "../../api/types";
import { money, pct } from "../../lib/format";
import { ArrowRight } from "../icons";
import { StateNotice } from "../StateNotice";
import { ErrorState, Skeleton } from "../ui";
import { AttributionPanel } from "./AttributionPanel";
import { AutoScenarioCard } from "./AutoScenarioCard";
import { ConcentrationPanel } from "./ConcentrationPanel";
import { MaterialityPanel } from "./MaterialityPanel";
import { PropagationChain } from "./PropagationChain";

function ImpactSummary({ r }: { r: AutoStressResult }) {
  const run = r.run;
  if (!run) return r.note ? <div className="mt-4 max-w-[70ch]"><StateNotice tone="warn" what="Nothing was run" why={r.note} /></div> : null;
  if (run.status !== "COMPLETED" || !run.summary) {
    return <div className="mt-4 max-w-[70ch]"><StateNotice tone="info" what="The generated scenario produced no numbers" why={run.reason ?? run.status} /></div>;
  }
  const s = run.summary;
  const tone = s.pnl < 0 ? "text-neg" : s.pnl > 0 ? "text-pos" : "text-ink-2";
  return (
    <div className="mt-6 border-t border-rule pt-5" aria-label="Portfolio impact">
      <p className="eyebrow">Portfolio impact</p>
      <dl className="mt-2 grid max-w-[44rem] grid-cols-3 gap-4">
        <div><dt className="text-xs text-muted">Before</dt><dd className="num font-display text-xl">{money(s.baseline_value)}</dd></div>
        <div><dt className="text-xs text-muted">After</dt><dd className="num font-display text-xl">{money(s.stressed_value)}</dd></div>
        <div><dt className="text-xs text-muted">Modeled change</dt><dd className={`num font-display text-xl ${tone}`}>{money(s.pnl, { signed: true })} <span className="text-sm">({pct(s.pnl_pct, 2, true)})</span></dd></div>
      </dl>
      <p className="mt-2 max-w-[66ch] text-xs text-muted">A modeled change under the generated scenario’s assumptions, not a forecast. {run.audit.forced ? "Run as a what-if: below the trigger threshold or past a soft gate." : ""}</p>
      {r.chain && <p className="mt-2 max-w-[70ch] text-sm text-ink-2">{r.chain.summary}</p>}
    </div>
  );
}

/**
 * The event workflow: why it matters → my exposure → scenario → portfolio impact → why the portfolio moved → concentration and blind spots.
 * Everything here is a derived side-car of the event; it is hidden where the replay engine is not running.
 */
export function PropagationSection({ signalId, blindSpots = true, variant = "event" }: { signalId: string; blindSpots?: boolean; variant?: "event" | "stress" }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.propagation === true;
  const flow = usePropagation(signalId, on);
  const stress = usePortfolioStress(signalId);
  const conc = useConcentration(on && blindSpots);
  const overlaps = useOverlaps(signalId, on && blindSpots);
  if (!on) return null;
  if (flow.isLoading) return <Skeleton className="mt-6 h-40 w-full" />;
  if (flow.error) {
    if (flow.error instanceof ApiError && flow.error.status === 404) return null;
    return <div className="mt-6"><ErrorState error={flow.error as Error} retry={() => flow.refetch()} /></div>;
  }
  const f = flow.data;
  if (!f) return null;
  const ran = stress.data;
  const att = ran?.attribution ?? null;
  return (
    <div aria-label="From the event to the portfolio">
      {variant === "event" && <MaterialityPanel m={f.materiality} />}
      {variant === "event" && <PropagationChain g={f.graph} />}
      <AutoScenarioCard gen={f.scenario} running={stress.isPending} ran={!!ran?.run} onRun={(force) => stress.mutate({ force })} />
      {stress.error && <div className="mt-4"><ErrorState error={stress.error as Error} /></div>}
      {ran && <ImpactSummary r={ran} />}
      {att && <AttributionPanel att={att} />}
      {ran?.run && ran.run.status === "COMPLETED" && (
        <p className="mt-4 text-sm">
          <Link className="inline-flex items-center gap-1 text-ink underline underline-offset-2 hover:text-accent" to={`/stress?signal=${signalId}`}>
            Open Portfolio Stress for the catalog scenario and what-if severity <ArrowRight size={13} />
          </Link>
        </p>
      )}
      {blindSpots && variant === "event" && (conc.data || overlaps.data) && <ConcentrationPanel view={conc.data} overlaps={overlaps.data} />}
    </div>
  );
}

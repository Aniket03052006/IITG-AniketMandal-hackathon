import { Link } from "react-router-dom";
import type { RiskAssessment, RiskSignal, Scenario } from "../../api/types";
import { ThresholdNotice } from "../assessment/ThresholdNotice";
import { impactKind, KIND_LABEL } from "../../lib/impact";
import { ArrowRight } from "../icons";
import { KindBadge } from "../ProvenanceKind";
import { PropagationSection } from "../propagation/PropagationSection";
import { RelevancePanel } from "../scope/RelevancePanel";
import { StateNotice } from "../StateNotice";
import { Chapter } from "./Chapter";

/** Chapter 5: the hand-off. A scenario is an assumption someone chose, scaled by the impact; it is not a prediction. */
export function StressBridge({ s, scenario, threshold, a }: { s: RiskSignal; scenario?: Scenario; threshold: number; a?: RiskAssessment }) {
  const sevScore = a ? (a.severity?.score ?? null) : null;
  const impact = a ? (a.severity ? { score: a.severity.score } : null) : s.impact;
  const triggers = !!impact && impact.score >= threshold;
  const kind = impactKind(s);
  const level = s.scope.level;
  return (
    <Chapter
      id="stress"
      eyebrow="Stress"
      title="What a scenario does to the portfolio"
      lede={a ? "The severity score decides whether a mapped scenario is suggested and how hard it is applied to the portfolio in use (the synthetic wholesale-banking book unless you chose your own). The arithmetic is deterministic and shown." : "The impact estimate decides how hard a mapped scenario is applied to the portfolio in use (the synthetic wholesale-banking book unless you chose your own). The arithmetic is deterministic and shown."}
      badge={<KindBadge kind="scenario" />}
    >
      <div className="bridge">
        <div>
          <p className="eyebrow">Mapped scenario</p>
          <p className="mt-1 font-display text-xl font-semibold">{scenario?.name ?? "No scenario mapped"}</p>
          <p className="mt-1 max-w-[60ch] text-sm text-muted">
            {scenario ? `${scenario.description} Illustrative assumptions, not forecasts.` : "This event type has no template, so nothing is invented."}
          </p>
        </div>
        <div>
          <p className="eyebrow">Trigger</p>
          {a ? (
            <div className="mt-2">
              <ThresholdNotice score={sevScore} threshold={threshold} signalId={s.id} action={false} compact />
            </div>
          ) : impact ? (
            <p className="mt-1 text-ink-2">
              {triggers ? `Impact ${impact.score} meets the threshold (≥ ${threshold}).` : `Impact ${impact.score} is below the threshold (≥ ${threshold}); it can still run as a what-if.`}
              {triggers && kind !== "validated" && <span className="text-warn"> On {KIND_LABEL[kind].toLowerCase()} output.</span>}
            </p>
          ) : (
            <p className="mt-1 text-ink-2">No impact score, so nothing triggers.</p>
          )}
        </div>
        <div className="flex items-end">
          {impact ? (
            <Link className={triggers ? "btn btn-primary" : "btn"} to={`/stress?signal=${s.id}${triggers ? "&run=1" : ""}`}>
              {triggers ? "Run scenario" : "Run as what-if"} <ArrowRight size={14} />
            </Link>
          ) : (
            <span className="text-sm text-muted">Nothing to run without an impact score.</span>
          )}
        </div>
      </div>
      <RelevancePanel signalId={s.id} />
      <PropagationSection signalId={s.id} />
      {level !== "COMPANY" && (
        <div className="mt-5 max-w-[64ch]">
          <StateNotice
            tone={level === "UNRESOLVED" ? "warn" : "info"}
            what={level === "SECTOR" ? "Sector and market-wide shocks apply" : level === "MARKET" ? "Only market-wide shocks apply" : "Only market-wide shocks could apply"}
            why={
              level === "SECTOR"
                ? "No single company is named, so issuer shocks have nothing to attach to; the sector's shocks and the market-wide ones still run."
                : level === "MARKET"
                  ? "A market-wide event reaches the book through market factors (equity level, rates, spreads), not through one holding."
                  : "Nothing was identified for the shocks to attach to. If the scenario has no market-wide shock, no loss is computed rather than a zero reported."
            }
          />
        </div>
      )}
    </Chapter>
  );
}

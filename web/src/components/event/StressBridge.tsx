import { Link } from "react-router-dom";
import type { RiskSignal, Scenario } from "../../api/types";
import { impactKind, KIND_LABEL } from "../../lib/impact";
import { ArrowRight } from "../icons";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { Chapter } from "./Chapter";

/** Chapter 5: the hand-off. A scenario is an assumption someone chose, scaled by the impact; it is not a prediction. */
export function StressBridge({ s, scenario, threshold }: { s: RiskSignal; scenario?: Scenario; threshold: number }) {
  const impact = s.impact;
  const triggers = !!impact && impact.score >= threshold;
  const kind = impactKind(s);
  const unresolved = s.entity.entity_id === "UNKNOWN_ENTITY";
  return (
    <Chapter
      id="stress"
      eyebrow="Stress"
      title="What a scenario does to the portfolio"
      lede="The impact estimate decides how hard a mapped scenario is applied to a synthetic wholesale-banking book. The arithmetic is deterministic and shown."
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
          {impact ? (
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
      {unresolved && (
        <div className="mt-5 max-w-[64ch]">
          <StateNotice
            tone="warn"
            what="Only market-wide shocks can apply"
            why="No company was linked to this story, so company-specific shocks have nothing to attach to. The scenario's market-wide shocks still run."
          />
        </div>
      )}
    </Chapter>
  );
}

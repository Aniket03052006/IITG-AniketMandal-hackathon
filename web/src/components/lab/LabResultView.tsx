import type { AssumptionResult, LabResult, ScenarioRequest } from "../../api/types";
import { WhyScenario } from "../explain/InlineWhy";
import { money, pct } from "../../lib/format";
import { ASSUMPTION_LABEL, SIMULATION_LABEL, fmt } from "../../lib/lab";
import { HistoryCheckView } from "../portfolio/HistoryCheck";
import { AttributionPanel } from "../propagation/AttributionPanel";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";

const TYPE_LABEL = { BASE: "Base", ASSESSED: "Assessed", CUSTOM: "Custom" } as const;

function Assumptions({ rows }: { rows: AssumptionResult[] }) {
  if (rows.length === 0) return <p className="text-sm text-ink-2">No assumptions: the portfolio as it is.</p>;
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[40rem]">
        <caption className="sr-only">The assumptions of this scenario and what each reached</caption>
        <thead>
          <tr><th scope="col">Assumption</th><th scope="col">Size</th><th scope="col">Reached</th><th scope="col" className="text-right">Modeled change</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={`${a.index}-${a.kind}-${a.description}`}>
              <td>
                <span className="font-medium text-ink">{a.description}</span>
                <span className="mt-1 flex flex-wrap items-center gap-2"><KindBadge kind="scenario" label={a.origin === "ASSESSED" ? "ASSUMPTION · EventShock's, not yours" : ASSUMPTION_LABEL} /></span>
                {a.rationale && <span className="mt-1 block text-xs text-muted">{a.rationale}</span>}
                {a.shocks.length > 1 && (
                  <ul className="mt-1 list-none p-0 text-xs text-muted">{a.shocks.map((s) => <li key={`${s.factor}-${s.sector}`}>{s.basis}</li>)}</ul>
                )}
              </td>
              <td className="num">{fmt(a.value, a.unit)}</td>
              <td>
                {a.reach === "NOT_REACHED" ? <StatusTag tone="warn">Reaches nothing</StatusTag> : a.origin === "USER" ? `${a.positions_reached} position${a.positions_reached === 1 ? "" : "s"} · ${pct(a.share_reached, 0)} of the book` : "Applied"}
                {a.note && <span className="mt-1 block text-xs text-muted">{a.note}</span>}
              </td>
              <td className="num text-right">{a.pnl != null ? money(a.pnl, { signed: true }) : "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A finished scenario: before and after, the assumptions with what each reached, why the portfolio moved, and a history reality check. A simulation, never a prediction. */
export function LabResultView({ r, req }: { r: LabResult; req?: ScenarioRequest }) {
  const s = r.result?.summary;
  return (
    <section className="card card-pad space-y-4" aria-label={`Result of ${r.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusTag tone="demo">{TYPE_LABEL[r.scenario_type]}</StatusTag>
        <KindBadge kind="scenario" label={SIMULATION_LABEL} />
        <span className="num text-xs text-muted" title="The same assumptions on the same portfolio always give this id">{r.scenario_id}</span>
      </div>
      <h3 className="font-display text-lg font-semibold">{r.name}</h3>
      {r.status !== "COMPLETED" && (
        <StateNotice tone="info" what={r.status === "UNAVAILABLE" ? "This scenario is not available" : "Nothing in the portfolio was moved"} why={r.reason ?? "The shocks reach no position."} />
      )}
      {s && (
        <div className="rhero-figures" role="group" aria-label="Portfolio value before and after">
          <div><p className="eyebrow">Before</p><p className="rhero-num num">{money(s.baseline_value)}</p></div>
          <div><p className="eyebrow">After</p><p className="rhero-num num">{money(s.stressed_value)}</p></div>
          <div>
            <p className="eyebrow">Change</p>
            <p className={`rhero-num num ${s.pnl < 0 ? "text-neg" : s.pnl > 0 ? "text-pos" : "text-ink-2"}`}>{money(s.pnl, { signed: true })}</p>
            <p className="num text-sm text-muted">{pct(s.pnl_pct, 2, true)} of the book</p>
          </div>
        </div>
      )}
      <Assumptions rows={r.assumptions} />
      {r.exposure_priors.length > 0 && (
        <div className="rounded-sm border border-rule bg-paper-3 p-3 text-sm" aria-label="Oil exposure estimated from sector priors">
          <p className="font-medium text-ink">Oil exposure was estimated, not measured.</p>
          <p className="mt-1 text-ink-2">Positions with no measured oil elasticity took their sector's prior ({r.exposure_priors.map((p) => `${p.sector} ${p.sensitivity.toFixed(2)} on ${p.positions} position${p.positions === 1 ? "" : "s"}`).join("; ")}). These are judgement priors: unvalidated assumptions.</p>
        </div>
      )}
      {r.attribution && <AttributionPanel att={r.attribution} />}
      {r.history_check && (
        <details className="disclosure">
          <summary>How large are these shocks by historical standards?</summary>
          <div className="mt-3"><HistoryCheckView check={r.history_check} /></div>
        </details>
      )}
      {req && r.status === "COMPLETED" && <WhyScenario req={req} />}
      <p className="text-xs text-muted">{r.note}</p>
    </section>
  );
}

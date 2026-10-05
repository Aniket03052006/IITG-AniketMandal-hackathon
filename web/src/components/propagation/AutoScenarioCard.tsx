import type { GeneratedScenario } from "../../api/types";
import { FACTOR_LABEL, SCOPE_LABEL, shockValue } from "../../lib/format";
import { SOURCE_LABEL } from "../../lib/propagation";
import { Check, Close, Play, Spinner } from "../icons";
import { StateNotice } from "../StateNotice";
import { AdjustedChip } from "./AdjustedChip";
import { StatusChip } from "./StatusChip";

/**
 * The scenario an event implies for this portfolio. Always labelled a simulation. When no defensible scenario exists it says SCENARIO UNAVAILABLE and which
 * gate failed; a soft gate (severity, relevance, direction) can still be run as a what-if.
 */
export function AutoScenarioCard({ gen, onRun, running, ran }: { gen: GeneratedScenario; onRun: (force: boolean) => void; running: boolean; ran: boolean }) {
  const s = gen.scenario;
  const available = gen.availability === "AVAILABLE";
  return (
    <div className="mt-6 border-t border-rule pt-5" aria-label="Scenario generated for this event">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Scenario</p>
        <AdjustedChip notice={gen.adjustments} />
      </div>
      <p className="mt-2 inline-block rounded-sm border border-dashed border-ink-2 bg-paper-2 px-2.5 py-1 text-sm font-semibold tracking-wide text-ink" role="note">
        {gen.label}
      </p>
      {!available && (
        <div className="mt-3 max-w-[70ch]">
          <StateNotice
            tone={gen.can_force ? "info" : "warn"}
            what="SCENARIO UNAVAILABLE"
            why={(gen.reason ?? "").replace(/^SCENARIO UNAVAILABLE:\s*/, "")}
            next={
              gen.can_force ? (
                <button type="button" className="btn" disabled={running} onClick={() => onRun(true)}>
                  {running ? <Spinner size={14} /> : <Play size={13} />} Run as a what-if anyway
                </button>
              ) : undefined
            }
          />
        </div>
      )}
      {gen.gates.length > 0 && (
        <ul className="mt-3 grid max-w-[60rem] gap-1 text-sm" aria-label="Conditions for generating a scenario">
          {gen.gates.map((g) => (
            <li key={g.id} className="flex items-start gap-2">
              {g.passed ? <Check size={14} className="mt-0.5 shrink-0 text-pos" /> : <Close size={14} className="mt-0.5 shrink-0 text-neg" />}
              <span>
                <span className={g.passed ? "text-ink-2" : "font-medium text-ink"}>{g.label}</span>
                <span className="text-muted"> · {g.detail}</span>
                <span className="sr-only">{g.passed ? " (met)" : " (not met)"}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {s && (
        <>
          <p className="mt-4 text-sm text-ink-2">
            <span className="font-medium">{s.name}.</span> {s.shocks.length} shocks at severity-scaled sizes; each is a judgement, none is a forecast.
          </p>
          <details className="disclosure mt-3" open={s.shocks.length <= 8}>
            <summary>The shocks and where each comes from</summary>
            <table className="mt-3 w-full max-w-[60rem] text-sm">
              <caption className="sr-only">Shocks of the generated scenario, at the scenario's reference severity</caption>
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th scope="col" className="pb-1 pr-3 font-medium">Shock</th>
                  <th scope="col" className="pb-1 pr-3 font-medium">Applies to</th>
                  <th scope="col" className="pb-1 pr-3 text-right font-medium">Size</th>
                  <th scope="col" className="pb-1 font-medium">Origin</th>
                </tr>
              </thead>
              <tbody>
                {s.shocks.map((sh, i) => {
                  const o = gen.origins.find((x) => x.factor === sh.factor && x.scope === sh.scope && (x.sector ?? null) === (sh.sector ?? null));
                  return (
                    <tr key={`${sh.factor}-${sh.scope}-${sh.sector ?? ""}-${i}`} className="border-t border-rule align-top">
                      <th scope="row" className="py-1.5 pr-3 text-left font-normal">{FACTOR_LABEL[sh.factor] ?? sh.factor}</th>
                      <td className="py-1.5 pr-3 text-muted">{sh.scope === "SECTOR" && sh.sector ? sh.sector : (SCOPE_LABEL[sh.scope] ?? sh.scope)}</td>
                      <td className="num py-1.5 pr-3 text-right">{shockValue(sh.factor, sh.value)}</td>
                      <td className="py-1.5">
                        {o && (
                          <>
                            <span className="mr-2 text-xs text-muted">{SOURCE_LABEL[o.source] ?? o.source}</span>
                            <StatusChip status={o.status} />
                            <span className="mt-0.5 block text-xs text-muted">{o.basis}</span>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        </>
      )}
      {available && (
        <div className="mt-4">
          <button type="button" className="btn btn-primary" disabled={running} data-loading={running} onClick={() => onRun(false)}>
            {running ? <Spinner size={14} /> : <Play size={13} />} {running ? "Running" : ran ? "Run again" : "Run on my portfolio"}
          </button>
        </div>
      )}
    </div>
  );
}

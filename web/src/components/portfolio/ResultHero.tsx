import clsx from "clsx";
import type { RiskSignal, StressResult } from "../../api/types";
import { money, moneyFull, pct } from "../../lib/format";
import { lifecycleKind } from "../../lib/impact";
import { useTween } from "../../lib/motion";
import { ImpactLifecycleTag } from "../ImpactLifecycleTag";
import { KindBadge } from "../ProvenanceKind";
import { StatusTag } from "../ui";
import { ValueBridge } from "./ValueBridge";

/** The payoff: portfolio value before and after, the change in dollars and percent, drawn to scale, with what was not reached. */
export function ResultHero({ r, onShowAssumptions }: { r: StressResult; s?: RiskSignal; onShowAssumptions: () => void }) {
  const sum = r.summary;
  const before = useTween(sum?.baseline_value ?? 0);
  const after = useTween(sum?.stressed_value ?? 0);
  const pnl = useTween(sum?.pnl ?? 0);
  if (!sum || !r.scenario || !r.severity) return null;
  const lossFrac = Math.min(1, Math.max(0, -sum.pnl / sum.baseline_value));
  const unc = r.uncovered;
  const tone = sum.pnl < 0 ? "text-neg" : sum.pnl > 0 ? "text-pos" : "text-ink-2";
  return (
    <section className="rhero hero-surface" aria-label="Portfolio value before and after the scenario">
      <div className="flex flex-wrap items-center gap-2">
        <KindBadge kind="scenario" label="Scenario simulation" />
        <StatusTag tone="ok">Deterministic engine</StatusTag>
        {r.audit.impact_overridden ? (
          <StatusTag tone="demo">What-if severity {r.severity.impact_used}</StatusTag>
        ) : (
          r.audit.impact_origin === "ASSESSMENT" ? (
            <StatusTag tone="demo">
              Severity {r.severity.impact_used} · {r.audit.extraction_mode === "LLM" ? "AI-assisted" : "rule-based"} · transparent weights, not validated
            </StatusTag>
          ) : (
            r.audit.impact_origin && <ImpactLifecycleTag kind={r.audit.impact_origin === "MODEL" ? lifecycleKind(r.audit.impact_lifecycle) : "placeholder"} detail="impact that triggered this" />
          )
        )}
      </div>

      <div className="rhero-figures">
        <div>
          <p className="eyebrow">Portfolio value</p>
          <p className="rhero-num num">{money(before)}</p>
          <p className="num text-xs text-muted">{moneyFull(sum.baseline_value)}</p>
        </div>
        <div className="rhero-arrow" aria-hidden="true" />
        <div>
          <p className="eyebrow">After the scenario</p>
          <p className="rhero-num num">{money(after)}</p>
          <p className="num text-xs text-muted">{moneyFull(sum.stressed_value)}</p>
        </div>
        <div>
          <p className="eyebrow">Estimated scenario change</p>
          <p className={clsx("rhero-num num", tone)}>{money(pnl, { signed: true })}</p>
          <p className={clsx("num text-md font-medium", tone)}>{pct(sum.pnl_pct, 2, true)} of portfolio value</p>
        </div>
      </div>

      <ValueBridge r={r} key={r.run_id} />

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div>
          <div className="scale-bar" role="img" aria-label={`Drawn to scale: the scenario removes ${pct(lossFrac, 2)} of portfolio value`}>
            <span className="scale-keep" style={{ width: `${(1 - lossFrac) * 100}%` }} />
            <span className="scale-lost" style={{ width: `${Math.max(lossFrac * 100, 0.4)}%` }} />
          </div>
          <p className="mt-1 text-xs text-muted">Drawn to scale: the part removed is {pct(lossFrac, 2)} of the book.</p>
        </div>
        {unc && unc.asset_count > 0 && (
          <div>
            <div className="scale-bar" role="img" aria-label={`${pct(unc.share_of_portfolio, 1)} of portfolio value was outside the scenario's reach`}>
              <span className="scale-reached" style={{ width: `${(1 - unc.share_of_portfolio) * 100}%` }} />
              <span className="scale-unreached" style={{ width: `${unc.share_of_portfolio * 100}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted">
              <strong className="font-medium text-ink-2">{pct(unc.share_of_portfolio, 1)} of the book ({unc.asset_count} positions) was outside this scenario's reach</strong> (hatched). Not treated as safe: nothing applied to it.
            </p>
          </div>
        )}
      </div>

      <p className="mt-4 text-sm text-muted">
        <span className="text-ink-2">{r.scenario.name}</span>: illustrative assumptions, scaled by the event's impact, not forecasts.{" "}
        <button type="button" className="text-accent underline underline-offset-2" onClick={onShowAssumptions}>
          Show assumptions
        </button>
      </p>
    </section>
  );
}

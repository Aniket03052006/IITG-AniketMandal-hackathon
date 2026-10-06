import { useState } from "react";
import { useLabOptions, useReverseStress } from "../../api/hooks";
import type { ReverseStressResult, ScenarioRequest, ScenarioRequestOut } from "../../api/types";
import { money, pct } from "../../lib/format";
import { ASSUMPTION_LABEL, fmt } from "../../lib/lab";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { WhyReverse } from "../explain/InlineWhy";
import { ErrorState, StatusTag } from "../ui";

const STATUS_TONE = { ACHIEVABLE: "ok", NOT_ACHIEVABLE: "warn", NO_EXPOSURE: "warn" } as const;
const STATUS_TEXT = { ACHIEVABLE: "Achievable", NOT_ACHIEVABLE: "Not achievable within the bounds", NO_EXPOSURE: "Nothing in the basket reaches this book" } as const;
const signedPct = (x: number, d = 2) => `${x < 0 ? "−" : x > 0 ? "+" : ""}${Math.abs(x).toFixed(d)}%`;

export function ReverseResultView({ r, onFork, askedFor }: { r: ReverseStressResult; onFork?: (req: ScenarioRequest) => void; askedFor?: { target_pct: number; exposure_priors: boolean } }) {
  const status = r.status as keyof typeof STATUS_TEXT;
  return (
    <section className="card card-pad space-y-4" aria-label="Reverse stress result">
      <div className="flex flex-wrap items-center gap-2">
        <StatusTag tone={STATUS_TONE[status] ?? "warn"}>{STATUS_TEXT[status] ?? r.status}</StatusTag>
        <KindBadge kind="scenario" label="Hypothetical stress analysis" />
        <span className="num text-xs text-muted">{r.reverse_id}</span>
      </div>

      <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-3" aria-label="Target and result">
        <div><dt className="eyebrow">Target</dt><dd className="rhero-num num">{signedPct(r.target_pct, 1)}</dd></div>
        <div><dt className="eyebrow">Achieved</dt><dd className="rhero-num num">{r.achieved_pct != null ? signedPct(r.achieved_pct, 2) : "–"}</dd>{r.difference_pp != null && <p className="num text-xs text-muted">{r.difference_pp >= 0 ? "+" : "−"}{Math.abs(r.difference_pp).toFixed(3)} pp from the target{r.status === "NOT_ACHIEVABLE" ? " (short of it)" : ""}</p>}</div>
        <div><dt className="eyebrow">Status</dt><dd className="mt-1 font-medium">{STATUS_TEXT[status] ?? r.status}</dd>{r.achieved_pnl != null && r.baseline_value != null && <p className="num text-xs text-muted">{money(r.achieved_pnl, { signed: true })} on {money(r.baseline_value)}</p>}</div>
      </dl>

      {r.status === "NO_EXPOSURE" && <StateNotice tone="info" what="No shock in the basket reaches this portfolio." why="Every axis either reaches nothing or only gains in its adverse direction, so no combination can lose money here." />}
      {r.status === "NOT_ACHIEVABLE" && <StateNotice tone="warn" what="The configured bounds cannot reach this loss." why={`The largest loss they allow is ${r.achieved_pct != null ? signedPct(r.achieved_pct, 2) : "n/a"}, with ${r.binding_bounds.join(", ")} at their limit.`} />}

      {r.required_shocks.length > 0 && (
        <div>
          <p className="eyebrow">{r.status === "ACHIEVABLE" ? "Required shocks" : "Shocks at the limit"}</p>
          <ul className="mt-2 list-none space-y-2 p-0" aria-label="Required shocks">
            {r.required_shocks.map((s) => (
              <li key={s.axis} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="font-medium text-ink">{s.label}{s.target && s.kind === "SECTOR" ? "" : ""}</span>
                <span className="num">{fmt(s.value, s.unit)}</span>
                <span className="text-xs text-muted">{pct(s.share_of_bound, 0)} of its limit ({fmt(s.unit === "bp" ? s.bound : s.value < 0 ? -s.bound : s.bound, s.unit)})</span>
                <KindBadge kind="scenario" label={ASSUMPTION_LABEL} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {r.dominant_drivers.length > 0 && (
        <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
          <div><dt className="eyebrow">Dominant driver</dt><dd className="mt-1">{r.dominant_drivers[0]}</dd></div>
          <div><dt className="eyebrow">Affected holdings</dt><dd className="mt-1 text-sm">{r.affected_holdings.join(", ") || "–"}</dd></div>
          <div><dt className="eyebrow">Affected sectors</dt><dd className="mt-1 text-sm">{r.affected_sectors.join(", ") || "–"}</dd></div>
          <div><dt className="eyebrow">Affected risk factors</dt><dd className="mt-1 text-sm">{r.affected_risk_factors.join(", ") || "–"}</dd></div>
        </dl>
      )}

      {r.exposure_priors.length > 0 && <p className="text-sm text-ink-2">Oil exposure was estimated from sector priors ({r.exposure_priors.map((p) => p.sector).join(", ")}): a judgement prior, not a measurement.</p>}

      <div className="flex flex-wrap items-center gap-2">
        {onFork && r.open_in_lab && <button type="button" className="btn" onClick={() => onFork(r.open_in_lab as ScenarioRequestOut as ScenarioRequest)}>Open in the lab</button>}
        {askedFor && <WhyReverse req={askedFor} />}
      </div>

      <details className="disclosure">
        <summary>Bounds and how it searched</summary>
        <div className="mt-3 space-y-3">
          <div className="scroll-x">
            <table className="dtable min-w-[36rem]">
              <caption className="sr-only">The basket's configured bounds</caption>
              <thead><tr><th scope="col">Axis</th><th scope="col">Limit</th><th scope="col">Adverse direction</th><th scope="col">Used</th></tr></thead>
              <tbody>
                {r.bounds.map((b) => (
                  <tr key={b.axis}>
                    <td>{b.label}{b.note && <span className="block text-xs text-muted">{b.note}</span>}</td>
                    <td className="num">{b.unit === "fraction" ? `${(b.bound * 100).toFixed(0)}%` : `${b.bound} ${b.unit}`}</td>
                    <td>{b.direction === "ADVERSE_DOWN" ? "down" : "up"}</td>
                    <td>{b.used ? "Yes" : "No"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-ink-2"><strong>Method:</strong> {r.search_method.replace(/_/g, " ").toLowerCase()}. {String(r.search_config.objective)}. {r.evaluations} engine evaluations; tolerance {String(r.search_config.tolerance_pp)} pp.</p>
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{[...r.assumptions, ...r.limitations].map((t) => <li key={t}>{t}</li>)}</ul>
        </div>
      </details>
      <p className="text-xs text-muted">{r.note}</p>
    </section>
  );
}

/** "What would it take to lose X%?": the hypothetical shocks, found by a bounded deterministic search and valued by the unchanged engine. Not a prediction of future losses. */
export function ReverseStress({ onFork }: { onFork?: (req: ScenarioRequest) => void }) {
  const opts = useLabOptions();
  const m = useReverseStress();
  const presets = opts.data?.reverse?.presets_pct ?? [-2, -5, -10];
  const [target, setTarget] = useState<string>("");
  const [priors, setPriors] = useState(false);
  const value = Number(target);
  const valid = target.trim() !== "" && Number.isFinite(value) && value < 0 && value >= (opts.data?.reverse?.min_target_pct ?? -95);
  const go = (t: number) => { setTarget(String(t)); m.mutate({ target_pct: t, exposure_priors: priors }); };
  return (
    <section aria-label="Reverse stress" className="space-y-3">
      <div className="max-w-[72ch]">
        <p className="eyebrow">Reverse stress</p>
        <h3 className="font-display text-lg font-semibold">What would it take to lose…?</h3>
        <p className="mt-1 text-sm text-ink-2">Pick a loss. EventShock searches, within configured bounds, for a combination of shocks that would reach it, valued by the same engine. A hypothetical, not a prediction of future losses.</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div role="group" aria-label="Target loss" className="flex flex-wrap gap-2">
          {presets.map((t) => <button key={t} type="button" className="chip" aria-pressed={Number(target) === t} onClick={() => go(t)}>{signedPct(t, 0)}</button>)}
        </div>
        <label>
          <span className="eyebrow block">Custom loss (%)</span>
          <input className="field num mt-1 w-28" inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="e.g. -7.5" aria-label="Custom target loss in percent" />
        </label>
        <button type="button" className="btn btn-primary" disabled={!valid || m.isPending} onClick={() => m.mutate({ target_pct: value, exposure_priors: priors })}>{m.isPending ? "Searching…" : "Find the shocks"}</button>
        <label className="flex items-center gap-2 pb-2 text-sm"><input type="checkbox" checked={priors} onChange={(e) => setPriors(e.target.checked)} /> Estimate oil exposure from sector priors</label>
      </div>
      {target.trim() !== "" && !valid && <p role="status" className="text-sm text-warn">Enter a loss between {opts.data?.reverse?.min_target_pct ?? -95}% and 0% (for example -5).</p>}
      {m.error && <ErrorState error={m.error as Error} />}
      {m.data && <ReverseResultView r={m.data} onFork={onFork} askedFor={{ target_pct: m.data.target_pct, exposure_priors: priors }} />}
    </section>
  );
}

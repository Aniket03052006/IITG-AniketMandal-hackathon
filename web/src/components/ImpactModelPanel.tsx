import clsx from "clsx";
import { useState } from "react";
import { useImpactModel } from "../api/hooks";
import type { ImpactCalibrationBin, ImpactEstimate, ImpactModelCard, ImpactScopeCard, ImpactSetResult } from "../api/types";
import { pct } from "../lib/format";
import { KIND_LABEL, LIFECYCLE_STEPS, lifecycleKind } from "../lib/impact";
import { ImpactLifecycleTag } from "./ImpactLifecycleTag";
import { Card, ErrorState, Loading, Stat } from "./ui";

const SCOPE_NAME: Record<string, string> = { ISSUER: "Issuer events", MARKET: "Market-wide events" };
const SCOPE_NOTE: Record<string, string> = {
  ISSUER: "One resolved listed company. Target: its abnormal return over the next two sessions, in units of its own usual volatility.",
  MARKET: "No listed company named (macro, geopolitics). Target: the S&P 500's own excess move over the next two sessions, in units of its usual volatility.",
};
const f3 = (x: number | null | undefined) => (x == null ? "–" : x.toFixed(3));
const fs = (x: number | null | undefined) => (x == null ? "–" : `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(3)}`);

function Est({ e, signed = false }: { e: ImpactEstimate; signed?: boolean }) {
  if (e.value == null) return <span className="text-muted">–</span>;
  const f = signed ? fs : f3;
  return (
    <span>
      <span className="font-medium text-ink">{f(e.value)}</span>
      {e.lo != null && e.hi != null && (
        <span className="block text-xs text-muted">
          {f(e.lo)} to {f(e.hi)}
        </span>
      )}
    </span>
  );
}

function Stepper({ scope }: { scope: ImpactScopeCard }) {
  const at = LIFECYCLE_STEPS.findIndex((s) => s.id === scope.lifecycle);
  return (
    <ol className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-6" aria-label={`Lifecycle of the ${SCOPE_NAME[scope.scope]} model`}>
      {LIFECYCLE_STEPS.map((st, i) => (
        <li key={st.id} aria-current={i === at ? "step" : undefined} className={clsx("border-t-2 pt-2 text-xs", i < at ? "border-pos" : i === at ? "border-warn" : "border-rule")}>
          <p className={clsx("num font-medium", i === at ? "text-ink" : "text-muted")}>
            {i + 1} · {st.label}
          </p>
          <p className={clsx("mt-0.5", i === at ? "text-ink-2" : "text-muted")}>{i < at ? "reached" : i === at ? "current" : "not reached"}</p>
        </li>
      ))}
    </ol>
  );
}

function Acceptance({ scope }: { scope: ImpactScopeCard }) {
  const a = scope.acceptance;
  if (!a.checks.length) return <p className="text-sm text-muted">No acceptance checks: {scope.summary}</p>;
  return (
    <>
      <p className="text-xs text-muted">{a.rule}</p>
      <ul className="mt-2 max-w-[84ch] space-y-1.5 text-sm text-ink-2">
        {a.checks.map((c) => (
          <li key={c.id} className="flex items-start gap-2">
            <span className={clsx("num mt-0.5 w-[3.2rem] shrink-0 text-xs font-medium", c.passed === true ? "text-pos" : c.passed === false ? "text-warn" : "text-muted")}>
              {c.passed === true ? "PASS" : c.passed === false ? "FAIL" : "N/A"}
            </span>
            <span className="min-w-0">
              <span className="num text-muted">{c.id}</span> {c.label}
              <span className="num block text-xs text-muted">{c.value}</span>
              <span className="block text-xs text-muted">{c.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function Ladder({ scope }: { scope: ImpactScopeCard }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[46rem]">
        <caption className="sr-only">Candidate models tried in order, scored out of fold on the training period</caption>
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col" className="text-right">Features</th>
            <th scope="col" className="text-right">Error (log-severity)</th>
            <th scope="col" className="text-right">Rank correlation</th>
            <th scope="col">Decision</th>
          </tr>
        </thead>
        <tbody>
          {scope.ladder.map((e) => (
            <tr key={e.id} className={clsx(e.chosen && "bg-paper-3")}>
              <td>
                <span className="num font-medium text-ink">{e.id}</span>
                {e.chosen && <span className="ml-2 text-xs text-ink-2">selected</span>}
                <span className="block text-xs text-muted">{e.servable ? "servable" : e.family === "constant" ? "baseline" : "diagnostic only"}</span>
              </td>
              <td className="num text-right text-muted">{e.n_features || "–"}</td>
              <td className="num text-right"><Est e={e.oof_mae} /></td>
              <td className="num text-right"><Est e={e.oof_spearman} signed /></td>
              <td className="max-w-[34ch] text-xs text-ink-2">{e.verdict}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Results({ scope }: { scope: ImpactScopeCard }) {
  const sets = scope.evaluations;
  const [sel, setSel] = useState(sets.find((s) => s.id === "val+test")?.id ?? sets[sets.length - 1]?.id ?? "");
  const cur: ImpactSetResult | undefined = sets.find((s) => s.id === sel) ?? sets[0];
  if (!cur) return null;
  const pick = scope.selected_id;
  return (
    <>
      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label="Evaluation set">
        {sets.map((s) => (
          <button key={s.id} type="button" className="chip" aria-pressed={s.id === cur.id} onClick={() => setSel(s.id)}>
            {s.id === "oof" ? "out-of-fold" : s.id}
          </button>
        ))}
      </div>
      <p className="mb-2 max-w-[84ch] text-xs text-muted">
        {cur.title}: <span className="num">{cur.n_episodes}</span> episodes (<span className="num">{cur.n_rows.toLocaleString("en-US")}</span> rows), {cur.period}. {cur.role}.
      </p>
      <div className="scroll-x">
        <table className="dtable min-w-[56rem]">
          <caption className="sr-only">Every candidate on the chosen evaluation set, against the baselines</caption>
          <thead>
            <tr>
              <th scope="col">Model</th>
              <th scope="col" className="text-right">Error</th>
              <th scope="col" className="text-right">vs constant</th>
              <th scope="col" className="text-right">Rank corr.</th>
              <th scope="col" className="text-right">Placebo rank corr.</th>
              <th scope="col" className="text-right">Top-decile lift</th>
            </tr>
          </thead>
          <tbody>
            {cur.models.map((m) => (
              <tr key={m.id} className={clsx(m.id === pick && "bg-paper-3")}>
                <td className="num">
                  {m.id}
                  {m.id === pick && <span className="ml-2 text-xs text-ink-2">selected</span>}
                </td>
                <td className="num text-right"><Est e={m.mae} /></td>
                <td className="num text-right"><Est e={m.delta_mae_vs_constant} signed /></td>
                <td className="num text-right"><Est e={m.spearman} signed /></td>
                <td className="num text-right text-muted"><Est e={m.placebo_spearman} signed /></td>
                <td className="num text-right text-muted">{m.top_decile_lift != null ? `${m.top_decile_lift.toFixed(2)}×` : "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 max-w-[84ch] text-xs text-muted">
        Error is mean absolute error of ln(1 + |z|), lower is better; “vs constant” is the paired difference (negative = better than always guessing the training average). Rank correlation is across episodes (a company on a day),
        with a 95% bootstrap interval that resamples episodes, never rows. The placebo column asks the same model to “predict” the window <em>before</em> the report: if it scores as well there, it is reading market state, not the event.
      </p>
    </>
  );
}

function Bins({ title, bins, nominal }: { title: string; bins: ImpactCalibrationBin[]; nominal?: string }) {
  return (
    <div className="scroll-x">
      <table className="dtable min-w-[34rem]">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            <th scope="col">Predicted score</th>
            <th scope="col" className="text-right">Episodes</th>
            <th scope="col" className="text-right">Median realised |z|</th>
            <th scope="col" className="text-right">Realised score (10–90%)</th>
            <th scope="col" className="text-right">Extreme move</th>
          </tr>
        </thead>
        <tbody>
          {bins.map((b) => (
            <tr key={`${b.score_low}-${b.score_high}`}>
              <td className="num">{b.score_low === b.score_high ? b.score_low : `${b.score_low}–${b.score_high}`}</td>
              <td className="num text-right">{b.n_episodes}</td>
              <td className="num text-right">{b.severity_q50.toFixed(2)}σ</td>
              <td className="num text-right">{b.realised_score_q10}–{b.realised_score_q90}</td>
              <td className="num text-right"><Est e={b.p_extreme} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {nominal && <p className="mt-1 text-xs text-muted">{nominal}</p>}
    </div>
  );
}

function ScopeBody({ card, scope }: { card: ImpactModelCard; scope: ImpactScopeCard }) {
  const kind = lifecycleKind(scope.lifecycle);
  const cal = scope.calibration;
  const t = scope.training;
  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <ImpactLifecycleTag kind={kind} detail={scope.lifecycle.toLowerCase()} />
        <span className="text-sm text-ink-2">{scope.served ? "Served" : "Not served: the labelled placeholder rule keeps scoring these"}</span>
      </div>
      <p className="mt-3 max-w-[78ch] text-sm text-ink-2">{scope.summary}</p>
      <p className="mt-2 max-w-[78ch] text-xs text-muted">{SCOPE_NOTE[scope.scope]}</p>
      <div className="mt-4"><Stepper scope={scope} /></div>

      <h3 className="mt-6 mb-2 text-sm font-semibold">Acceptance bar</h3>
      <Acceptance scope={scope} />

      <h3 className="mt-6 mb-2 text-sm font-semibold">Models tried, in order, scored out of fold</h3>
      <p className="mb-2 max-w-[84ch] text-xs text-muted">{card.selection_rule}. Each fold trains only on sessions at least five sessions before the fold starts.</p>
      <Ladder scope={scope} />

      <h3 className="mt-6 mb-2 text-sm font-semibold">Baseline vs model on later periods</h3>
      <Results scope={scope} />

      {cal && (
        <>
          <h3 className="mt-6 mb-2 text-sm font-semibold">What each score has meant historically</h3>
          <p className="mb-2 max-w-[84ch] text-xs text-muted">{cal.method}.</p>
          <p className="mb-1 text-xs font-medium text-ink-2">Reference: out-of-fold training period, {cal.reference_period} ({cal.reference_episodes.toLocaleString("en-US")} episodes)</p>
          <Bins title="Reference calibration" bins={cal.bins_reference} />
          <p className="mt-4 mb-1 text-xs font-medium text-ink-2">Independent check: 2022 validation + test, same buckets</p>
          <Bins title="Held-out calibration" bins={cal.bins_heldout} />
          <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
            <Stat label="Extreme-move base rate" value={pct(cal.base_rate_extreme, 1)} sub={`realised score ≥ ${cal.extreme_score}`} />
            <Stat label="Interval coverage" value={cal.heldout_coverage.value != null ? pct(cal.heldout_coverage.value, 0) : "–"} sub={`served 10–90% range; nominal ${pct(cal.nominal_coverage, 0)}`} />
            <Stat label="Bucket order" value={cal.monotonicity_spearman != null ? cal.monotonicity_spearman.toFixed(2) : "n/a"} sub="rank corr. of bucket vs realised |z|" />
            <Stat label="Extreme-move Brier" value={cal.extreme_brier != null ? cal.extreme_brier.toFixed(4) : "–"} sub={cal.extreme_brier_base_rate != null ? `base-rate guess ${cal.extreme_brier_base_rate.toFixed(4)}` : ""} />
          </div>
        </>
      )}

      {scope.strata.length > 0 && (
        <>
          <h3 className="mt-6 mb-2 text-sm font-semibold">Where it works and where it does not (val + test)</h3>
          <div className="scroll-x">
            <table className="dtable min-w-[40rem]">
              <caption className="sr-only">Held-out performance by slice</caption>
              <thead>
                <tr>
                  <th scope="col">Slice</th>
                  <th scope="col" className="text-right">Episodes</th>
                  <th scope="col" className="text-right">Rank corr.</th>
                  <th scope="col" className="text-right">Error: model</th>
                  <th scope="col" className="text-right">Error: constant</th>
                </tr>
              </thead>
              <tbody>
                {scope.strata.map((s) => (
                  <tr key={`${s.dimension}-${s.value}`}>
                    <td>
                      <span className="text-ink-2">{s.value.replace(/_/g, " ").toLowerCase()}</span>
                      <span className="block text-xs text-muted">{s.dimension}</span>
                    </td>
                    <td className="num text-right">{s.n_episodes}</td>
                    <td className="num text-right"><Est e={s.spearman} signed /></td>
                    <td className="num text-right">{f3(s.mae_model)}</td>
                    <td className="num text-right text-muted">{f3(s.mae_constant)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-rule pt-5 sm:grid-cols-4">
        <Stat label="Training rows" value={t.rows.train?.toLocaleString("en-US") ?? "–"} sub={`${t.episodes.train?.toLocaleString("en-US") ?? "–"} episodes · ${t.train_period}`} />
        <Stat label="Held out" value={`${(t.episodes.val ?? 0) + (t.episodes.test ?? 0)}`} sub={`episodes: val ${t.episodes.val ?? 0}, test ${t.episodes.test ?? 0}`} />
        <Stat label="Live news" value={`${t.episodes.live ?? 0}`} sub="2026 episodes, scored once" />
        <Stat label="Artifact" value={`${(card.artifact_bytes / 1e6).toFixed(2)} MB`} sub={<span className="num">sha256 {card.artifact_sha256.slice(0, 12)}</span>} />
      </div>
      <p className="mt-3 max-w-[84ch] text-xs text-muted">
        {scope.algorithm}. Seed <span className="num">{t.seed}</span>; {t.folds}. Config sha256 <span className="num">{t.config_sha256.slice(0, 12)}</span>, table sha256 <span className="num">{t.table_sha256.slice(0, 12)}</span>.
      </p>

      {scope.attribution && (
        <p className="mt-2 max-w-[84ch] text-xs text-muted">
          Explanations: {scope.attribution.exact ? "exact (an additive model; baseline plus contributions equals the prediction)" : `${scope.attribution.kind} (each feature moved alone from its typical value; they do not sum exactly, worst gap ${scope.attribution.max_abs_error ?? "?"} in ${scope.attribution.units.split(":")[0]})`}.
        </p>
      )}
      {scope.horizon.length > 0 && (
        <p className="mt-2 max-w-[84ch] text-xs text-muted">
          Horizon check (rank correlation, val + test): {scope.horizon.map((h) => `${h.window_sessions} session${h.window_sessions > 1 ? "s" : ""} ${fs(h.spearman.value)}`).join(" · ")}. The target stays two sessions.
        </p>
      )}
      {scope.direction && (
        <p className="mt-2 max-w-[84ch] text-xs text-muted">
          Direction (not part of the score): confident sentiment matched the sign of the realised move {scope.direction.hit_rate.value != null ? pct(scope.direction.hit_rate.value, 0) : "–"} of the time over {scope.direction.n} documents
          {scope.direction.hit_rate.lo != null ? ` (95%: ${pct(scope.direction.hit_rate.lo, 0)} to ${pct(scope.direction.hit_rate.hi ?? 0, 0)})` : ""}; 50% is a coin flip.
        </p>
      )}

      <h3 className="mt-6 mb-2 text-sm font-semibold">Leakage checks that ran</h3>
      <ul className="max-w-[84ch] list-disc space-y-1 pl-5 text-xs text-ink-2">
        {scope.leakage_findings.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>

      <h3 className="mt-6 mb-2 text-sm font-semibold">Limits you should know about</h3>
      <ul className="max-w-[72ch] list-disc space-y-1.5 pl-5 text-sm text-ink-2">
        {scope.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </>
  );
}

function Body({ card }: { card: ImpactModelCard }) {
  const [scopeId, setScopeId] = useState(card.scopes[0]?.scope ?? "ISSUER");
  const scope = card.scopes.find((s) => s.scope === scopeId) ?? card.scopes[0];
  return (
    <>
      <p className="max-w-[78ch] text-sm text-ink-2">
        The question this answers: does information available <em>when a report appears</em> predict how large the market's reaction is, better than a simple baseline? {card.output_definition} Evaluated only on later periods than it was fitted on,
        with a five-session embargo. The acceptance bar in <span className="num">configs/impact_model.yaml</span> was fixed before the first held-out run.
      </p>
      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Model scope">
        {card.scopes.map((s) => (
          <button key={s.scope} type="button" className="chip" aria-pressed={s.scope === scope?.scope} onClick={() => setScopeId(s.scope)}>
            {SCOPE_NAME[s.scope] ?? s.scope} · {KIND_LABEL[lifecycleKind(s.lifecycle)].toLowerCase()}
          </button>
        ))}
      </div>
      <div className="mt-5 border-t border-rule pt-4">{scope && <ScopeBody card={card} scope={scope} />}</div>
    </>
  );
}

export function ImpactModelPanel({ enabled }: { enabled: boolean }) {
  const { data, error, isLoading, refetch } = useImpactModel(enabled);
  return (
    <Card title="Impact model" aside={data ? <span className="num">{data.id}</span> : undefined}>
      {error ? <ErrorState error={error} retry={() => refetch()} /> : isLoading || !data ? <Loading label="Loading model card" /> : <Body card={data} />}
    </Card>
  );
}

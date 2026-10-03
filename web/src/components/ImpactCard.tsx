import clsx from "clsx";
import { Link } from "react-router-dom";
import { useImpactModel, useScenarios } from "../api/hooks";
import type { ImpactAudit, ImpactScopeCard, RiskSignal } from "../api/types";
import { dateTime, pct } from "../lib/format";
import { impactKind, KIND_LABEL, type ImpactKind } from "../lib/impact";
import { severityBand } from "../lib/severity";
import { ImpactDrivers } from "./ImpactDrivers";
import { ImpactLifecycleTag } from "./ImpactLifecycleTag";
import { ArrowRight, Check, Info } from "./icons";
import { Card, ImpactMeter, InlineNote, StatusTag } from "./ui";

const TIMING_TEXT: Record<string, string> = {
  OFF_HOURS: "after the close or on a non-trading day: the whole reaction follows the report",
  PRE_OPEN: "before the open",
  IN_SESSION: "during the session: part of the move may precede the report",
  DATE_ONLY: "the source gave a date but no time",
  FIRST_SEEN: "a crawl time, which lags publication: the reaction may precede it",
};

/** Plain-language names for the inputs worth showing next to a prediction (all of them stay in the audit). */
const INPUT_NAME: Record<string, string> = {
  f_sigma_60: "Issuer's usual daily move (60-session volatility)",
  m_sigma_60: "Market's usual daily move (60-session volatility)",
  f_vix_level: "VIX the session before",
  m_vix_level: "VIX the session before",
  f_ret_5d: "Issuer's return, last 5 sessions",
  m_ret_5d: "S&P 500 return, last 5 sessions",
  f_resid_vol_5d_ratio: "Recent vs usual volatility (5 sessions)",
  f_volume_ratio: "Volume vs its 20-session norm",
  novelty: "Novelty of the report (1 = nothing similar in 72 h)",
};
const PCT_INPUTS = new Set(["f_sigma_60", "m_sigma_60", "f_ret_5d", "m_ret_5d"]);

function fmtInput(k: string, v: number): string {
  if (PCT_INPUTS.has(k)) return pct(v, 2);
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}

function Evidence({ audit, s }: { audit: ImpactAudit; s: RiskSignal }) {
  const shown = Object.keys(INPUT_NAME).filter((k) => k in audit.inputs);
  const sc = audit.session === "NEXT" ? "the next session (not yet traded)" : audit.session;
  return (
    <>
      <h3 className="mt-6 mb-2 text-sm font-semibold">What the model knew when this appeared</h3>
      <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-ink-2">Event type (text model)</dt>
        <dd className="num text-right">{s.event.status === "CLASSIFIED" ? s.event.category.replace(/_/g, " ").toLowerCase() : s.event.status.replace("_", " ").toLowerCase()}</dd>
        <dt className="text-ink-2">Sentiment (text model)</dt>
        <dd className="num text-right">{s.sentiment.score >= 0 ? "+" : "−"}{Math.abs(s.sentiment.score).toFixed(2)}</dd>
        {shown.map((k) => (
          <div key={k} className="contents">
            <dt className="text-ink-2">{INPUT_NAME[k]}</dt>
            <dd className="num text-right">{fmtInput(k, audit.inputs[k] ?? 0)}</dd>
          </div>
        ))}
        <dt className="text-ink-2">Reaction measured from</dt>
        <dd className="num text-right">{sc}</dd>
      </dl>
      <p className="mt-2 max-w-[70ch] text-xs text-muted">
        Everything here was known before the reaction session: prices up to the previous close, the report's own wording, and its timestamp. Nothing is read from later reports of the same story
        (the number of outlets, for example, is deliberately not an input). Market data as of {audit.market_context_as_of}.
      </p>
      {!audit.timing_reliable && (
        <div className="mt-3">
          <InlineNote tone="warn" title="Timestamp is the weak link">
            This report's time is {TIMING_TEXT[audit.timing] ?? audit.timing}. The model's evidence on such timestamps is thinner, so treat the score as less certain than the range suggests.
          </InlineNote>
        </div>
      )}
    </>
  );
}

function ModelReadout({ s, audit, scope, kind }: { s: RiskSignal; audit: ImpactAudit; scope: ImpactScopeCard | undefined; kind: ImpactKind }) {
  const i = s.impact!;
  const band = severityBand(i.score);
  const range: [number, number] | null = i.score_low != null && i.score_high != null ? [i.score_low, i.score_high] : null;
  return (
    <>
      <div className="grid grid-cols-1 gap-x-8 gap-y-5 sm:grid-cols-3">
        <div>
          <p className="eyebrow">Model prediction</p>
          <p className="num mt-1 text-2xl font-medium">{i.predicted_severity!.toFixed(2)}σ</p>
          <p className="mt-0.5 text-xs text-muted">
            expected size of the {audit.scope === "MARKET" ? "S&P 500's" : "issuer's"} abnormal move over the next two sessions, in units of its usual daily volatility (the raw model output)
          </p>
        </div>
        <div>
          <p className="eyebrow">EventShock score</p>
          <div className="mt-1">
            <ImpactMeter score={i.score} size="lg" range={range} kind={kind} />
          </div>
          <p className={clsx("mt-1 text-xs font-medium", band.text)}>{band.label} · {KIND_LABEL[kind].toLowerCase()}</p>
          <p className="mt-0.5 text-xs text-muted">
            the prediction ranked against {i.comparable_events != null ? "historical events" : "its training history"}; the bracket is what comparable events actually realised{range ? ` (${range[0]} to ${range[1]})` : ""}
          </p>
        </div>
        <div>
          <p className="eyebrow">Chance of an extreme move</p>
          <p className="num mt-1 text-2xl font-medium">{i.p_extreme != null ? pct(i.p_extreme, 1) : "–"}</p>
          <p className="mt-0.5 text-xs text-muted">
            of {i.comparable_events?.toLocaleString("en-US") ?? "–"} comparable past events realised a move of 3σ or more (score 7+); about {scope?.calibration ? pct(scope.calibration.base_rate_extreme, 1) : "–"} of all events do
          </p>
        </div>
      </div>
      <p className="mt-4 max-w-[64ch] text-sm text-muted">
        A guide to how large a market reaction to this report is likely to be. It is not a probability of loss, not a direction and not a price forecast.
      </p>
    </>
  );
}

function ExperimentalNote({ scope }: { scope: ImpactScopeCard | undefined }) {
  if (!scope) return null;
  const failed = scope.acceptance.checks.filter((c) => c.passed !== true);
  return (
    <div className="mt-4">
      <InlineNote tone="warn" title={`${KIND_LABEL[scope.lifecycle === "PRODUCTION" ? "validated" : "experimental"]}: ${scope.lifecycle.toLowerCase()}, not production`}>
        {scope.summary.split(" Acceptance:")[0]} {failed.length > 0 && `Not met: ${failed.map((c) => c.label.toLowerCase()).join("; ")}. `}
        <Link to="/pipeline" className="underline underline-offset-2 hover:text-ink">See the validation</Link>.
      </InlineNote>
    </div>
  );
}

/** The impact estimate of one signal: raw prediction, calibrated 1-10 score, uncertainty, drivers, evidence and provenance, labelled by what produced it. */
export function ImpactCard({ s, threshold }: { s: RiskSignal; threshold: number }) {
  const scenarios = useScenarios();
  const kind = impactKind(s);
  const audit = s.provenance?.impact ?? null;
  const card = useImpactModel(!!audit);
  const scope = audit ? card.data?.scopes.find((x) => x.scope === audit.scope) : undefined;
  const scenarioId = scenarios.data?.default_by_category[s.event.category];
  const scenario = scenarios.data?.scenarios.find((x) => x.id === scenarioId);
  const impact = s.impact;
  const triggers = !!impact && impact.score >= threshold;
  const band = impact ? severityBand(impact.score) : null;
  const fixture = s.data_origin === "DEMO_FIXTURE";

  return (
    <Card title="Impact assessment" aside={
        !impact ? "Market-response proxy, 1 to 10" : fixture ? <StatusTag tone="demo">Fixture · illustrative</StatusTag> : <ImpactLifecycleTag kind={kind} detail={audit ? audit.scope.toLowerCase() + " scope" : undefined} />
      } className="h-full">
      {!impact ? (
        <InlineNote tone="warn" title={s.event.status === "CLASSIFIED" ? "Impact unavailable for this signal" : "No impact scored for this signal"}>
          {s.status_reason} EventShock never substitutes a default score, so this signal cannot trigger a stress test.
        </InlineNote>
      ) : (
        <>
          {audit && impact.predicted_severity != null ? (
            <>
              <ModelReadout s={s} audit={audit} scope={scope} kind={kind} />
              {kind !== "validated" && <ExperimentalNote scope={scope} />}
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
                <ImpactMeter score={impact.score} size="lg" kind={fixture ? undefined : "placeholder"} />
                <div className="pb-1">
                  <p className={clsx("font-display text-lg font-semibold", band?.text)}>{band?.label} impact{fixture ? "" : " · placeholder rule"}</p>
                  <p className="num text-xs text-muted">
                    raw {impact.raw.toFixed(2)} → {impact.quantisation}
                  </p>
                </div>
              </div>
              <p className="mt-3 max-w-[64ch] text-sm text-muted">
                {fixture ? "A hand-authored fixture value." : "A hand-set rule, not a measurement: it has no uncertainty and has never been tested against market outcomes."} It is not a probability of loss and not a price forecast.
              </p>
              {s.provenance?.impact_note && (
                <div className="mt-3">
                  <InlineNote title="Why the trained model did not score this">{s.provenance.impact_note}.</InlineNote>
                </div>
              )}
            </>
          )}

          <h3 className="mt-6 mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm font-semibold">
            {audit ? "What drives the estimate" : "What drives the score"}
            <StatusTag tone="demo">{audit ? "Model attributions · from the model's own inputs" : fixture ? "Fixture drivers · illustrative, not SHAP" : "Placeholder heuristic · not a trained model"}</StatusTag>
          </h3>
          <ImpactDrivers impact={impact} />

          {audit && <Evidence audit={audit} s={s} />}

          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-rule pt-5">
            <div className="min-w-0 text-sm">
              <p className="flex items-center gap-2 font-medium">
                {triggers ? <Check size={15} className="text-sev-high" /> : <Info size={15} className="text-muted" />}
                {triggers ? `Meets the trigger threshold (≥ ${threshold})` : `Below the trigger threshold (≥ ${threshold})`}
                {triggers && !fixture && kind !== "validated" && <span className="text-xs font-normal text-warn">on {KIND_LABEL[kind].toLowerCase()} output</span>}
              </p>
              <p className="mt-1 text-muted">
                {scenario ? (
                  <>
                    Maps to <span className="text-ink-2">{scenario.name}</span>, an illustrative template.
                  </>
                ) : (
                  "Scenario mapping loading…"
                )}
              </p>
            </div>
            <Link to={`/stress?signal=${s.id}${triggers ? "&run=1" : ""}`} className={clsx("btn", triggers && "btn-primary")}>
              {triggers ? "Run stress test" : "Run as what-if"} <ArrowRight size={14} />
            </Link>
          </div>

          {audit && (
            <p className="num mt-4 border-t border-rule pt-3 text-xs text-muted">
              {audit.model_id} · sha256 {audit.artifact_sha256.slice(0, 12)} · {audit.feature_schema} · {audit.lifecycle.toLowerCase()} · scored {dateTime(s.created_at)}
            </p>
          )}
        </>
      )}
    </Card>
  );
}

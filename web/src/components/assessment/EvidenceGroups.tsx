import type { EvidenceView } from "../../api/types";
import { dateTime } from "../../lib/format";
import { AssessmentKind } from "./AssessmentKind";
import { HighlightedText } from "./HighlightedText";

/** Three kinds of support, kept in three boxes so they cannot be mistaken for one another. */
export function EvidenceGroups({ ev }: { ev: EvidenceView }) {
  const src = ev.source_evidence;
  const inf = ev.model_inference;
  const sc = ev.scenario_assumptions;
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <section className="card p-5" aria-label="Source evidence">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Source evidence</h3>
          <AssessmentKind kind="SOURCE" />
        </div>
        <p className="mt-1 text-xs text-muted">{src.note}</p>
        <blockquote className="quote mt-3 !text-base">
          <HighlightedText text={src.text} spans={src.spans} />
        </blockquote>
        {src.entity_match && <p className="mt-2 text-xs text-muted">Entity: {src.entity_match}.</p>}
        <ul className="mt-3 space-y-2" aria-label="Reports of this story">
          {src.reports.map((r, i) => (
            <li key={`${r.source}-${i}`} className="text-sm">
              <span className="font-medium text-ink">{r.source}</span>{" "}
              <span className="num text-xs text-muted">{dateTime(r.published_at)}</span>
              <br />
              <span className="text-xs text-muted">
                {r.relation === "THIS_REPORT" ? "this report" : r.phase === "AFTER_REPORT" ? "published afterwards: shown, never scored" : "existed at the time: counted"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="card p-5" aria-label="Model inference">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Model inference</h3>
          <AssessmentKind kind="EXTRACTION" />
        </div>
        <p className="mt-1 text-xs text-muted">{inf.note}</p>
        <dl className="mt-3 space-y-3">
          {inf.lines.slice(0, 4).map((l) => (
            <div key={l.label}>
              <dt className="flex flex-wrap items-center gap-2 text-xs text-muted">
                {l.label} <AssessmentKind kind={l.kind} />
              </dt>
              <dd className="mt-0.5 text-sm text-ink">
                {l.value}
                {l.detail && <span className="block text-xs text-muted">{l.detail}</span>}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-xs text-muted">{inf.agreement.note}</p>
      </section>

      <section className="card p-5" aria-label="Scenario assumptions">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Scenario assumptions</h3>
          <AssessmentKind kind="SCENARIO_ASSUMPTION" />
        </div>
        <p className="mt-1 text-xs text-muted">{sc.note}</p>
        {sc.scenario_name ? (
          <>
            <p className="mt-3 font-display text-lg font-semibold">{sc.scenario_name}</p>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-2">
              {sc.shocks.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
            <p className="num mt-3 text-xs text-muted">{sc.severity_scaling}</p>
            <p className="mt-1 text-xs text-muted">Trigger: severity at or above {sc.trigger_threshold}. Illustrative assumptions, not forecasts.</p>
          </>
        ) : (
          <p className="mt-3 text-sm text-ink-2">No scenario applies, so no assumption is invented.</p>
        )}
      </section>
    </div>
  );
}

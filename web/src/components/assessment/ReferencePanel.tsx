import type { RiskAssessment } from "../../api/types";
import { lifecycleKind, KIND_LABEL } from "../../lib/impact";
import { ImpactLifecycleTag } from "../ImpactLifecycleTag";
import { ImpactMeter } from "../ui";
import { AssessmentKind } from "./AssessmentKind";

/** The trained market-reaction model, next to the severity score and clearly secondary. It measures how big an abnormal price move may be; it does not drive the trigger. */
export function ReferencePanel({ a }: { a: RiskAssessment }) {
  const r = a.reference;
  const kind = lifecycleKind(r.lifecycle);
  return (
    <details className="card p-5">
      <summary className="cursor-pointer text-sm font-semibold text-ink">
        Reference: the trained market-reaction model {r.available && r.score != null ? `says ${r.score}/10` : "gave no score"}
      </summary>
      <div className="mt-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <AssessmentKind kind="MODEL_REFERENCE" />
          {r.origin === "MODEL" ? <ImpactLifecycleTag kind={kind} /> : r.available ? <span className="tag">{KIND_LABEL.placeholder}</span> : null}
          {r.model_id && <span className="num text-xs text-muted">{r.model_id}</span>}
        </div>
        {r.available && r.score != null && (
          <ImpactMeter score={r.score} range={r.score_low != null && r.score_high != null ? [r.score_low, r.score_high] : null} kind={kind} showKind wide />
        )}
        <p className="max-w-[70ch] text-sm text-ink-2">{r.note}</p>
        <p className="max-w-[70ch] text-xs text-muted">
          Its pre-registered acceptance bar was not met: in its own evaluation the real window scored no better than a placebo window before the news, so its skill is
          mostly the volatility regime. That is why it is a reference here and the severity score above drives the trigger.
        </p>
      </div>
    </details>
  );
}

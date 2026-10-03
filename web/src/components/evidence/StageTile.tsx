import clsx from "clsx";
import type { StageStatus } from "../../api/types";
import { KIND_LABEL, type ImpactKind } from "../../lib/impact";
import { StatusTag } from "../ui";

const WHAT: Record<string, { name: string; does: string }> = {
  sentiment: { name: "Sentiment", does: "Reads the tone of the text, from negative to positive." },
  event: { name: "Event understanding", does: "Decides what kind of event a text describes, or abstains." },
  impact: { name: "Impact", does: "Estimates how severe the market reaction is likely to be." },
};

/** Passed / failed / not-evaluable as one row of marks: the count is the headline, the colour only reinforces. */
function CheckStrip({ passed, failed, na }: { passed: number; failed: number; na: number }) {
  const total = passed + failed + na;
  if (total === 0) return <p className="text-sm text-muted">No pre-registered checks exist for this stage.</p>;
  return (
    <div>
      <div className="strip" role="img" aria-label={`${passed} of ${total} checks passed, ${failed} not met, ${na} not evaluable`}>
        {Array.from({ length: passed }, (_, i) => (
          <i key={`p${i}`} className="strip-pass" />
        ))}
        {Array.from({ length: failed }, (_, i) => (
          <i key={`f${i}`} className="strip-fail" />
        ))}
        {Array.from({ length: na }, (_, i) => (
          <i key={`n${i}`} className="strip-na" />
        ))}
      </div>
      <p className="mt-2 text-sm text-ink-2">
        <span className="num font-medium text-ink">{passed}</span> of <span className="num">{total}</span> pre-registered checks passed
        {na > 0 ? `, ${na} not evaluable` : ""}.
      </p>
    </div>
  );
}

export function StageTile({ s }: { s: StageStatus }) {
  const kind = s.kind as ImpactKind;
  const info = WHAT[s.stage] ?? { name: s.stage, does: "" };
  const tone = kind === "validated" ? "ok" : kind === "experimental" ? "warn" : "demo";
  return (
    <article className="tile">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-display text-lg font-semibold">{info.name}</h3>
        <StatusTag tone={tone}>{KIND_LABEL[kind] ?? s.kind}</StatusTag>
      </div>
      <p className="mt-1 text-sm text-muted">{info.does}</p>
      <div className="mt-4">
        <CheckStrip passed={s.passed.length} failed={s.failed.length} na={s.not_evaluable.length} />
      </div>
      <p className="mt-3 text-sm text-ink-2">{kind === "validated" ? "Every pre-registered check passed." : "Not called validated."}</p>
      <details className="disclosure mt-3">
        <summary>What was and was not met</summary>
        <div className={clsx("mt-2 space-y-2 text-sm")}>
          <p className="text-ink-2">{s.summary}</p>
          {s.failed.length > 0 && (
            <p>
              <span className="font-medium text-warn">Not met:</span> <span className="text-ink-2">{s.failed.join("; ")}</span>
            </p>
          )}
          {s.not_evaluable.length > 0 && (
            <p className="text-muted">
              <span className="font-medium">Not evaluable:</span> {s.not_evaluable.join("; ")}
            </p>
          )}
          {s.passed.length > 0 && <p className="text-muted">Passed: {s.passed.join("; ")}</p>}
          <p className="num text-xs text-muted">{s.model_id ?? "no model loaded"}{s.artifact_sha256 ? ` · sha256 ${s.artifact_sha256.slice(0, 16)}…` : ""}</p>
        </div>
      </details>
    </article>
  );
}

/** The stress engine is not a model, so it has no acceptance bar: its evidence is that it is deterministic arithmetic you can check. */
export function EngineTile() {
  return (
    <article className="tile">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <h3 className="font-display text-lg font-semibold">Stress engine</h3>
        <StatusTag tone="ok">Deterministic</StatusTag>
      </div>
      <p className="mt-1 text-sm text-muted">Turns an impact score and a scenario into a revalued portfolio.</p>
      <div className="mt-4">
        <p className="text-sm text-ink-2">
          <span className="font-medium text-ink">Not a model.</span> Fixed formulas, no randomness: the same inputs always give the same result, checked by unit tests. What it cannot do is make the shocks true: they are illustrative assumptions.
        </p>
      </div>
      <details className="disclosure mt-3">
        <summary>What is and is not claimed</summary>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-ink-2">
          <li>Every position's change is reproducible from the formula shown with it.</li>
          <li>Shocks are chosen magnitudes per event type, scaled by impact: scenario assumptions, not forecasts.</li>
          <li>The portfolio is synthetic; results are not a statement about any real book.</li>
        </ul>
      </details>
    </article>
  );
}

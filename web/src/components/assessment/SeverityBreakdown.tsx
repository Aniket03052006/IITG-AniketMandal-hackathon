import type { RiskAssessment } from "../../api/types";
import { StateNotice } from "../StateNotice";
import { MarketNote } from "./MarketNote";
import { OriginChip } from "./OriginChip";
import { RubricTable } from "./RubricTable";
import { ScoreBuildUp } from "./ScoreBuildUp";

/** The severity chapter's body: the four answers, the build-up line by line, market data freshness, what was left out, reliability, the range and the caveats. */
export function SeverityBreakdown({ a }: { a: RiskAssessment }) {
  const sev = a.severity;
  if (!sev) return null;
  return (
    <div className="space-y-10">
      <section aria-labelledby="sev-rubric">
        <h3 id="sev-rubric" className="text-lg font-semibold">
          The four answers behind it
        </h3>
        <p className="mb-4 mt-1 max-w-[72ch] text-sm text-muted">
          Each answer starts from deterministic rules. If a language model read the text it may move an answer one step (more only with a verbatim quote), and always
          gives a reason. Both are shown, so you can see exactly what the AI changed.
        </p>
        <RubricTable rubric={sev.rubric} mode={a.extraction.mode} />
      </section>

      <section aria-labelledby="sev-build">
        <h3 id="sev-build" className="text-lg font-semibold">
          How the score is built
        </h3>
        <p className="mb-4 mt-1 max-w-[72ch] text-sm text-muted">
          A fixed matrix turns intensity and reach into points; certainty and direction scale them; two bounded data adjustments follow. Nothing else enters: not the tone, not
          how confident the AI is, not how many outlets reported it.
        </p>
        <ScoreBuildUp steps={sev.steps} score={sev.score} points={sev.points} />
      </section>

      <section className="grid gap-8 lg:grid-cols-2" aria-label="Data, reliability and range">
        <div className="space-y-4">
          <h3 className="text-sm font-semibold">Market data</h3>
          <MarketNote m={sev.market} />
          {sev.omitted
            .filter((o) => o.id !== "regime")
            .map((o) => (
              <p key={o.id} className="text-sm text-muted">
                <span className="font-medium text-ink-2">{o.label} not used:</span> {o.reason}
              </p>
            ))}
        </div>
        <div className="space-y-4">
          <div className="fact">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="eyebrow">Report reliability</p>
              <OriginChip origin="DATA" />
            </div>
            <p className="fact-value">{sev.reliability.level[0]!.toUpperCase() + sev.reliability.level.slice(1)}</p>
            <p className="mt-0.5 text-sm text-muted">
              {sev.reliability.basis}. {sev.reliability.note}
            </p>
          </div>
          <div className="fact">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="eyebrow">If the judgement parameters were different</p>
              <OriginChip origin="ASSUMPTION" />
            </div>
            <p className="fact-value num">
              {sev.low}–{sev.high}
            </p>
            <p className="mt-0.5 text-sm text-muted">
              {sev.range_basis}
              {sev.uncertainty != null ? ` The reading's own uncertainty (${Math.round(sev.uncertainty * 100)}%) widens the range; it never lowers the score.` : ""}
            </p>
          </div>
        </div>
      </section>

      {a.conflict && (
        <StateNotice tone="warn" what="Another report on the same issuer disagrees" why={`${a.conflict.note} “${a.conflict.headline}” (${a.conflict.hours_apart} h apart).`} />
      )}
      <details className="disclosure">
        <summary>The formula, as arithmetic</summary>
        <p className="num mt-3 rounded-md border border-rule bg-paper-2 p-3 text-xs text-ink-2">{sev.formula}</p>
      </details>
    </div>
  );
}

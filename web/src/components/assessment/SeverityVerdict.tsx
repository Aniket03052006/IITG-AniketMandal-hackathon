import clsx from "clsx";
import { Link } from "react-router-dom";
import type { RiskAssessment } from "../../api/types";
import { useTween } from "../../lib/motion";
import { severityBand } from "../../lib/severity";
import { ASSESSED_INPUTS, ExplainBar, SEVERITY_WHY, TECH } from "../event/ExplainBar";
import { StateNotice } from "../StateNotice";
import { StatusTag } from "../ui";
import { ModeChip } from "./ModeChip";
import { OriginChip, OriginLegend } from "./OriginChip";
import { ScaleBar } from "./ScaleBar";
import { ThresholdNotice } from "./ThresholdNotice";

/**
 * The verdict, readable in seconds: the score and its band on the five-band scale, the four answers behind it (each tagged hybrid), what the AI changed,
 * how reliable the report is, whether market data was used, and exactly what happens at the trigger.
 */
export function SeverityVerdict({ a, threshold }: { a: RiskAssessment; threshold: number }) {
  const sev = a.severity;
  const shown = Math.round(useTween(sev?.score ?? 0));
  if (!sev) {
    return (
      <div className="verdict">
        <p className="eyebrow">Severity</p>
        <div className="mt-3">
          <StateNotice
            tone="warn"
            what="Not treated as a market event"
            why={`${a.severity_note ?? "Nothing is scored for it."} EventShock never substitutes a default score, so this signal cannot trigger a stress test.`}
            next={
              <Link className="btn" to="/?min=7">
                Browse high-severity events
              </Link>
            }
          />
        </div>
      </div>
    );
  }
  const band = severityBand(sev.score);
  return (
    <div className="verdict" data-kind="assessment">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Severity</p>
        <ModeChip a={a} />
      </div>
      <div className="mt-2 flex items-end gap-3">
        <span className={clsx("verdict-score num", band.text)} aria-hidden="true">
          {shown}
        </span>
        <span className="pb-2 text-lg text-muted" aria-hidden="true">
          / 10
        </span>
        <span className="pb-2">
          <span className={clsx("block font-display text-xl font-semibold", band.text)}>{sev.band_label}</span>
          <span className="text-xs text-muted">{sev.band_says}</span>
        </span>
      </div>
      <div className="mt-5">
        <ScaleBar score={sev.score} />
        {sev.low !== sev.high && (
          <p className="mt-2 text-xs text-muted">
            Range {sev.low} to {sev.high} if the judgement parameters were different (assumption sensitivity, not a statistical interval).
          </p>
        )}
      </div>

      <ul className="mt-4 flex flex-wrap gap-1.5" aria-label="The four answers behind the score">
        {sev.rubric.map((f) => (
          <li key={f.id} className="tag" title={f.final_says}>
            <span className="text-muted">{f.label}:</span> {f.final_label}
            {f.adjustment === "AI_WITHIN_BOUND" || f.adjustment === "AI_QUOTE_BACKED" ? <span aria-label="moved by the AI"> ·AI</span> : null}
          </li>
        ))}
      </ul>

      <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-2">
        {a.extraction.mode === "RULES" ? (
          <>
            <OriginChip origin="RULES" />
            Deterministic rules only: no language model answered the rubric, so there is no AI adjustment.
          </>
        ) : (
          <>
            <OriginChip origin="HYBRID" />
            {sev.ai_effect === 0
              ? "The AI's bounded adjustments did not change the score."
              : `The AI's bounded adjustments moved it ${sev.ai_effect > 0 ? "up" : "down"} ${Math.abs(sev.ai_effect)} (rules alone: ${sev.baseline_score}).`}
          </>
        )}
      </p>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ink-2">
        <StatusTag tone={sev.reliability.level === "low" ? "warn" : "demo"}>Report reliability: {sev.reliability.level}</StatusTag>
        <StatusTag tone={sev.market.used ? "ok" : "warn"}>{sev.market.used ? `Market data ${sev.market.sessions_behind === 0 ? "current" : `${sev.market.sessions_behind} session behind`}` : "Market data not used"}</StatusTag>
      </p>

      <p className="mt-4 max-w-[52ch] text-ink-2">{a.summary}</p>
      <div className="mt-4">
        <ThresholdNotice score={sev.score} threshold={threshold} signalId={a.signal_id} compact />
      </div>
      <div className="mt-5">
        <ExplainBar items={[SEVERITY_WHY, ASSESSED_INPUTS, TECH]} />
      </div>
      <OriginLegend className="mt-5 border-t border-rule pt-4" />
    </div>
  );
}

import clsx from "clsx";
import { Link } from "react-router-dom";
import type { RiskAssessment } from "../../api/types";
import { useTween } from "../../lib/motion";
import { severityBand } from "../../lib/severity";
import { ExplainBar, SEVERITY_WHY, ASSESSED_INPUTS, TECH } from "../event/ExplainBar";
import { StateNotice } from "../StateNotice";
import { ImpactMeter } from "../ui";
import { AssessmentKind } from "./AssessmentKind";
import { ModeChip } from "./ModeChip";
import { ThresholdNotice } from "./ThresholdNotice";

/** The verdict: how serious, as a score that resolves once with its sensitivity range, who read the text, and exactly what happens at the trigger. */
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
        <span className="flex flex-wrap items-center gap-2">
          <ModeChip a={a} />
          <AssessmentKind kind="JUDGEMENT_PRIOR" />
        </span>
      </div>
      <div className="mt-2 flex items-end gap-3">
        <span className={clsx("verdict-score num", band.text)} aria-hidden="true">
          {shown}
        </span>
        <span className="pb-2 text-lg text-muted" aria-hidden="true">
          / 10
        </span>
        <span className="pb-2">
          <span className={clsx("block font-display text-xl font-semibold", band.text)}>{band.label}</span>
          <span className="text-xs text-muted">{a.extraction.mode === "LLM" ? "AI-assisted" : "Rule-based"} assessment · not validated</span>
        </span>
      </div>
      <div className="mt-4">
        <ImpactMeter score={sev.score} size="lg" noun="Severity" range={sev.low !== sev.high ? [sev.low, sev.high] : null} hideNumber wide />
        {sev.low !== sev.high && (
          <p className="mt-1 text-xs text-muted">
            Bracket: {sev.low} to {sev.high} if any one weight were off by 30% (assumption sensitivity, not a statistical interval).
          </p>
        )}
      </div>
      <p className="mt-4 max-w-[52ch] text-ink-2">{a.summary}</p>
      <div className="mt-4">
        <ThresholdNotice score={sev.score} threshold={threshold} signalId={a.signal_id} compact />
      </div>
      <div className="mt-5">
        <ExplainBar items={[SEVERITY_WHY, ASSESSED_INPUTS, TECH]} />
      </div>
    </div>
  );
}

import type { RiskAssessment } from "../../api/types";
import { driversLede } from "../../lib/assessment";
import { ASSESSED_INPUTS, ExplainBar, SEVERITY_WHY, TECH } from "../event/ExplainBar";
import { Chapter } from "../event/Chapter";
import { StateNotice } from "../StateNotice";
import { AssessmentKind } from "./AssessmentKind";
import { ReferencePanel } from "./ReferencePanel";
import { SeverityBreakdown } from "./SeverityBreakdown";

/** Chapter 3 when a risk assessment exists: how serious it is, and why, from the factors that were computed (not from a model's attribution). */
export function SeverityChapter({ a }: { a: RiskAssessment }) {
  const sev = a.severity;
  return (
    <Chapter
      id="impact"
      eyebrow="Severity"
      title="How serious it is, and why"
      lede={sev ? driversLede(sev) : "There is no severity to explain: the text is not a market event."}
      badge={<AssessmentKind kind="JUDGEMENT_PRIOR" />}
    >
      {sev ? (
        <SeverityBreakdown a={a} />
      ) : (
        <StateNotice tone="info" what="Nothing is scored" why={a.severity_note ?? "EventShock never substitutes a default score."} />
      )}
      <div className="mt-8">
        <ReferencePanel a={a} />
      </div>
      <div className="mt-6">
        <ExplainBar items={sev ? [SEVERITY_WHY, ASSESSED_INPUTS, TECH] : [TECH]} />
      </div>
      <ul className="mt-5 max-w-[72ch] list-disc space-y-1 pl-5 text-xs text-muted">
        {a.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </Chapter>
  );
}

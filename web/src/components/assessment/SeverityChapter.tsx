import type { RiskAssessment } from "../../api/types";
import { severityLede } from "../../lib/assessment";
import { ASSESSED_INPUTS, ExplainBar, SEVERITY_WHY, TECH } from "../event/ExplainBar";
import { Chapter } from "../event/Chapter";
import { StateNotice } from "../StateNotice";
import { OriginChip } from "./OriginChip";
import { ProvenanceStrip } from "./ProvenanceStrip";
import { ReferencePanel } from "./ReferencePanel";
import { SeverityBreakdown } from "./SeverityBreakdown";

/** Chapter 3 when a risk assessment exists: how serious it is and why, from four answers and a fixed matrix, with every part's origin stated. */
export function SeverityChapter({ a }: { a: RiskAssessment }) {
  const sev = a.severity;
  return (
    <Chapter
      id="impact"
      eyebrow="Severity"
      title="How serious it is, and why"
      lede={sev ? severityLede(sev) : "There is no severity to explain: the text is not a market event."}
      badge={<OriginChip origin={sev?.rubric.some((r) => r.origin === "HYBRID") ? "HYBRID" : "RULES"} />}
    >
      {sev ? (
        <SeverityBreakdown a={a} />
      ) : (
        <StateNotice tone="info" what="Nothing is scored" why={a.severity_note ?? "EventShock never substitutes a default score."} />
      )}
      <div className="mt-8">
        <ProvenanceStrip lines={a.provenance} />
      </div>
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

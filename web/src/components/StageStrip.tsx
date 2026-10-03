import type { Meta } from "../api/types";
import { KIND_LABEL, servedKinds } from "../lib/impact";
import { stageKind, stageName } from "../lib/provenance";
import { StatusTag } from "./ui";

const STAGES = ["sentiment", "event", "impact"] as const;

/** Which of the three NLP stages is a trained model and which is still a placeholder, straight from the pipeline report.
 *  The impact stage says more than "trained": an experimental model is not a validated one. */
export function StageStrip({ meta }: { meta: Meta | undefined }) {
  const origins = meta?.replay?.stage_origins;
  if (!origins) return null;
  const kinds = servedKinds(meta);
  return (
    <ul className="flex flex-wrap items-center gap-2" aria-label="What each stage is">
      {STAGES.map((k) => {
        const kind = stageKind(origins[k]);
        const impactText = k === "impact" && kind === "model" ? (kinds.length ? kinds.map((x) => KIND_LABEL[x].toLowerCase()).join(" / ") : "trained model") : null;
        const tone = k === "impact" && kind === "model" && !kinds.includes("validated") ? "warn" : kind === "model" ? "ok" : "warn";
        return (
          <li key={k}>
            <StatusTag tone={tone}>
              {stageName(k)}: {impactText ?? (kind === "model" ? "trained model" : "placeholder rules")}
            </StatusTag>
          </li>
        );
      })}
    </ul>
  );
}

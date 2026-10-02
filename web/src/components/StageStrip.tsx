import type { Meta } from "../api/types";
import { stageKind, stageName } from "../lib/provenance";
import { StatusTag } from "./ui";

const STAGES = ["sentiment", "event", "impact"] as const;

/** Which of the three NLP stages is a trained model and which is still a placeholder, straight from the pipeline report. */
export function StageStrip({ meta }: { meta: Meta | undefined }) {
  const origins = meta?.replay?.stage_origins;
  if (!origins) return null;
  return (
    <ul className="flex flex-wrap items-center gap-2" aria-label="What each stage is">
      {STAGES.map((k) => {
        const kind = stageKind(origins[k]);
        return (
          <li key={k}>
            <StatusTag tone={kind === "model" ? "ok" : "warn"}>
              {stageName(k)}: {kind === "model" ? "trained model" : "placeholder rules"}
            </StatusTag>
          </li>
        );
      })}
    </ul>
  );
}

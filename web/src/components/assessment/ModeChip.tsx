import type { LLMInfo, RiskAssessment } from "../../api/types";
import { Alert, Check, Info } from "../icons";
import { StatusTag } from "../ui";

/** One chip that says what read the text. A fallback is stated, never hidden. */
export function ModeChip({ a, llm }: { a?: Pick<RiskAssessment, "extraction">; llm?: LLMInfo | null }) {
  if (a) {
    const e = a.extraction;
    if (e.mode === "LLM") {
      return (
        <StatusTag tone="ok" icon={<Check size={12} />}>
          AI-assisted{e.cached ? " · cached" : ""}
        </StatusTag>
      );
    }
    return e.fallback_reason ? (
      <StatusTag tone="warn" icon={<Alert size={12} />}>
        Rules (model unavailable)
      </StatusTag>
    ) : (
      <StatusTag tone="demo" icon={<Info size={12} />}>
        Rule-based reading
      </StatusTag>
    );
  }
  if (!llm) return null;
  return llm.mode === "LLM" ? (
    <StatusTag tone="ok" icon={<Check size={12} />}>
      AI-assisted · {llm.model}
    </StatusTag>
  ) : (
    <StatusTag tone="demo" icon={<Info size={12} />}>
      Rule-based demo mode
    </StatusTag>
  );
}

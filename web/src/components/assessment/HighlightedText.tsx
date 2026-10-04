import { segments, SUPPORT_LABEL } from "../../lib/assessment";
import type { EvidenceSpan } from "../../api/types";

/** The analysed text with every quoted evidence span marked (tinted + underlined; the field it supports is in the tooltip). */
export function HighlightedText({ text, spans }: { text: string; spans: Pick<EvidenceSpan, "start" | "end" | "supports">[] }) {
  return (
    <p className="assess-text text-ink">
      {segments(text, spans).map((s, i) =>
        s.hit.length ? (
          <mark key={i} className="hl" title={`Evidence for: ${s.hit.map((h) => SUPPORT_LABEL[h] ?? h).join(", ")}`}>
            {s.text}
          </mark>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </p>
  );
}

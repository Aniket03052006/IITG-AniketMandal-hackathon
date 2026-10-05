import clsx from "clsx";
import type { RubricField } from "../../api/types";
import { OriginChip } from "./OriginChip";

const ADJ: Record<string, string> = {
  NONE: "Agreed",
  AI_WITHIN_BOUND: "AI moved it one step",
  AI_QUOTE_BACKED: "AI moved it further, backed by a quote",
  AI_CLAMPED: "AI held to one step",
  AI_IGNORED: "AI answer ignored",
};

/** The four rubric answers: what the deterministic rules said, what the AI proposed (with its reason and any verbatim quote), and what was used. */
export function RubricTable({ rubric, mode }: { rubric: RubricField[]; mode: "LLM" | "RULES" }) {
  return (
    <div className="rubric-grid" role="list" aria-label="The four rubric answers">
      {rubric.map((f) => (
        <article key={f.id} role="listitem" className="rubric-card">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-semibold text-ink">{f.label}</h4>
            <OriginChip origin={f.origin} />
          </div>
          <p className="mt-1 font-display text-lg font-semibold">{f.final_label}</p>
          <p className="text-xs text-muted">{f.final_says}</p>
          <dl className="mt-3 space-y-2 text-sm">
            <div>
              <dt className="flex flex-wrap items-center gap-2 text-xs text-muted">
                Rules said <OriginChip origin="RULES" />
              </dt>
              <dd className="text-ink-2">
                <span className="font-medium">{f.baseline_label}</span>: {f.baseline_basis.join("; ")}
              </dd>
            </div>
            <div>
              <dt className="flex flex-wrap items-center gap-2 text-xs text-muted">
                AI said <OriginChip origin="AI" />
              </dt>
              <dd className="text-ink-2">
                {f.ai_label ? (
                  <>
                    <span className="font-medium">{f.ai_label}</span>
                    {f.ai_reason && <>: {f.ai_reason}</>}
                    {f.ai_quote && <span className="block text-xs text-muted">Quoted: “{f.ai_quote}”</span>}
                  </>
                ) : (
                  <span className="text-muted">{mode === "RULES" ? "No language model read this text (rule-based mode)." : "No usable answer."}</span>
                )}
              </dd>
            </div>
          </dl>
          <p className={clsx("mt-3 text-xs", f.adjustment === "NONE" ? "text-muted" : "text-ink")}>
            <span className="font-medium">{ADJ[f.adjustment] ?? f.adjustment}.</span> {f.note}
          </p>
        </article>
      ))}
    </div>
  );
}

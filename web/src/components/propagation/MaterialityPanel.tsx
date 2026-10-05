import type { PortfolioMateriality } from "../../api/types";
import { LEVEL_LABEL, levelTone } from "../../lib/propagation";
import { pct } from "../../lib/format";
import { StatusTag } from "../ui";
import { AdjustButton, AdjustedChip } from "./AdjustedChip";

/** Why is this event relevant to this portfolio? The lookup, every input, and the rule that fired: no hidden weights. */
export function MaterialityPanel({ m }: { m: PortfolioMateriality }) {
  const abstained = m.availability === "ABSTAINED";
  return (
    <div aria-label="Why this event matters to this portfolio" className="mt-6 border-t border-rule pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="eyebrow">Why it matters to {m.portfolio_name ? `“${m.portfolio_name}”` : "this portfolio"}</p>
        <div className="flex flex-wrap items-center gap-2">
          <AdjustedChip notice={m.adjustments} />
          <AdjustButton />
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <StatusTag tone={levelTone(m.level)}>Relevance: {LEVEL_LABEL[m.level] ?? m.level}</StatusTag>
        {!abstained && m.reached_share > 0 && <span className="num text-sm text-ink-2">reaches {pct(m.reached_share)} of the book</span>}
      </div>
      <p className="mt-2 max-w-[66ch] text-ink-2">{m.summary}</p>
      {m.why.length > 0 && (
        <ol className="mt-3 max-w-[66ch] list-decimal space-y-1 pl-5 text-sm text-ink-2">
          {m.why.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ol>
      )}
      {m.components.length > 0 && (
        <details className="disclosure mt-4">
          <summary>Every input to this level</summary>
          <table className="mt-3 w-full max-w-[52rem] text-sm">
            <caption className="sr-only">Inputs to the relevance level</caption>
            <thead>
              <tr className="text-left text-xs text-muted">
                <th scope="col" className="pb-1 pr-4 font-medium">Input</th>
                <th scope="col" className="pb-1 pr-4 font-medium">Value</th>
                <th scope="col" className="pb-1 font-medium">What it is</th>
              </tr>
            </thead>
            <tbody>
              {m.components.map((c) => (
                <tr key={c.id} className="border-t border-rule align-top">
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal text-ink-2">{c.label}</th>
                  <td className="num py-1.5 pr-4">
                    {c.display}
                    {c.band && <span className="ml-2 text-xs text-muted">{c.band.replace("_", " ").toLowerCase()}</span>}
                  </td>
                  <td className="py-1.5 text-muted">{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.rules.length > 0 && (
            <ul className="mt-3 max-w-[60ch] space-y-1 text-sm" aria-label="Rules applied in order">
              {m.rules.map((r) => (
                <li key={r.id} className={r.fired ? "text-ink-2" : "text-muted"}>
                  <span className="font-medium">{r.kind === "GRID" ? "Lookup" : r.kind === "BUMP" ? "Bump" : "Cap"}</span>
                  {!r.fired && r.kind !== "GRID" ? " (did not apply)" : ""}: {r.effect}
                </li>
              ))}
            </ul>
          )}
        </details>
      )}
      <p className="mt-3 max-w-[66ch] text-xs text-muted">{m.labels.join(" ")}</p>
    </div>
  );
}

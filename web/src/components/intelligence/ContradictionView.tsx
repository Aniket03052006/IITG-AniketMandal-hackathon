import type { ClaimConflict, ContradictionView as View, IntelClaim } from "../../api/types";
import { CONFLICT_LABEL, hoursLabel, when } from "../../lib/intelligence";
import { StatusTag } from "../ui";

function Side({ c, label }: { c: IntelClaim; label: string }) {
  return (
    <div className="min-w-0 rounded-md border border-rule bg-paper-2 p-3">
      <p className="eyebrow">{label}</p>
      <p className="mt-1 font-medium text-ink">
        {c.source} says <span className="underline decoration-dotted underline-offset-4">{c.polarity}</span>
        {c.attributed && <span className="ml-2 tag">hedged or second-hand</span>}
      </p>
      <blockquote className="quote mt-2 text-sm">“{c.evidence_span.quote}”</blockquote>
      <p className="mt-2 text-xs text-muted">
        {when(c.published_at)} · subject {c.subject ?? "not stated"} · {c.full_text ? "read from the full report" : "read from the headline only"}
      </p>
    </div>
  );
}

function Conflict({ c }: { c: ClaimConflict }) {
  const tone = c.state === "CONFLICTED" ? "neg" : c.state === "POSSIBLE_CONFLICT" ? "warn" : c.state === "RESOLVED_CONFLICT" ? "ok" : "demo";
  return (
    <li className="rounded-lg border border-rule p-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusTag tone={tone}>{CONFLICT_LABEL[c.state]}</StatusTag>
        <span className="text-sm font-medium text-ink">{c.axis_label}</span>
        {c.hours_apart != null && <span className="text-xs text-muted">{hoursLabel(c.hours_apart)} apart</span>}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <Side c={c.side_a} label="One side" />
        <Side c={c.side_b} label="The other side" />
      </div>
      <p className="mt-3 text-sm text-ink-2">{c.reason}</p>
      {c.shared_topic.length > 0 && <p className="mt-1 text-xs text-muted">Topic words both clauses share: {c.shared_topic.join(", ")}.</p>}
      {c.resolved_by && (
        <p className="mt-2 text-sm text-ink-2">
          <span className="font-medium text-ink">{c.resolution}</span> “{c.resolved_by.evidence_span.quote}”
        </p>
      )}
    </li>
  );
}

/** Reports that disagree, both sides side by side with their source, time and verbatim clause. Tone alone is never shown as a contradiction. */
export function ContradictionPanel({ v }: { v: View }) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">
        <span className="font-medium text-ink">{CONFLICT_LABEL[v.state]}.</span> {v.claims_extracted} claim{v.claims_extracted === 1 ? "" : "s"} read from the reports.
        {v.reason && <> {v.reason}</>}
      </p>
      {v.conflicts.length > 0 && <ul className="space-y-3" aria-label="Conflicting claims">{v.conflicts.map((c) => <Conflict key={c.id} c={c} />)}</ul>}
      {v.sequential_changes.length > 0 && (
        <details className="disclosure">
          <summary>{v.sequential_changes.length} change{v.sequential_changes.length === 1 ? "" : "s"} of state over time (not contradictions)</summary>
          <ul className="mt-3 space-y-2">
            {v.sequential_changes.map((c) => (
              <li key={c.id} className="text-sm text-ink-2">{c.axis_label}: {c.reason}</li>
            ))}
          </ul>
        </details>
      )}
      {v.tone_divergence && (
        <p className="max-w-[72ch] text-sm text-muted">
          Context only, not a contradiction: another report on the same issuer {v.tone_divergence.hours_apart.toFixed(0)} h away reads with the opposite tone (“{v.tone_divergence.headline}”). Tone differs; no claim is opposed.
        </p>
      )}
      <p className="max-w-[72ch] text-xs text-muted">{v.method}</p>
    </div>
  );
}

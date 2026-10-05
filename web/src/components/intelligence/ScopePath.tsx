import type { EventScope } from "../../api/types";
import { RESOLUTION_LABEL, SCOPE_TYPE_LABEL, TIER_LABEL } from "../../lib/intelligence";

/** The hierarchy from the most specific subject up to the market. A level with no evidence is simply absent: nothing is filled in. */
export function ScopePath({ scope }: { scope: EventScope }) {
  if (scope.scope_path.length === 0) {
    return <p className="text-sm text-ink-2">No hierarchy: {scope.reason}</p>;
  }
  return (
    <ol className="flex flex-wrap items-center gap-x-2 gap-y-2" aria-label="Scope hierarchy, most specific first">
      {scope.scope_path.map((n, i) => (
        <li key={`${n.type}-${n.value}`} className="flex items-center gap-2">
          {i > 0 && <span aria-hidden="true" className="text-muted">→</span>}
          <span className="rounded-sm border border-rule bg-paper-2 px-2 py-1 text-sm" title={`basis: ${n.basis.toLowerCase().replaceAll("_", " ")}`}>
            <span className="eyebrow mr-1.5">{SCOPE_TYPE_LABEL[n.type] ?? n.type}</span>
            <span className="font-medium text-ink">{n.value}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** What the scope rests on: its status, its rule tier (not a probability) and the words in the text that support it. */
export function ScopeEvidence({ scope }: { scope: EventScope }) {
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink-2">{scope.reason}</p>
      <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        <div>
          <dt className="eyebrow">Resolution</dt>
          <dd>{RESOLUTION_LABEL[scope.resolution_status] ?? scope.resolution_status}</dd>
        </div>
        <div>
          <dt className="eyebrow">Confidence tier (a rule tier, not a probability)</dt>
          <dd>
            {TIER_LABEL[scope.scope_confidence.tier]}: {scope.scope_confidence.basis}
          </dd>
        </div>
      </dl>
      {scope.scope_confidence.measured && <p className="text-xs text-muted">Measured: {scope.scope_confidence.measured}.</p>}
      {scope.candidates.length > 0 && (
        <p className="text-ink-2">
          Also named, and not chosen between: <span className="font-medium text-ink">{scope.candidates.join(", ")}</span>.
        </p>
      )}
      {scope.scope_evidence.length > 0 && (
        <div>
          <p className="eyebrow">Words in the text that support it</p>
          <ul className="mt-1 flex flex-wrap gap-2">
            {scope.scope_evidence.map((e, i) => (
              <li key={`${e.dimension}-${e.term}-${i}`} className="tag" title={e.quote ? `at characters ${e.start}–${e.end}` : "matched after folding case and punctuation"}>
                {e.dimension.replaceAll("_", " ")}: {e.quote ?? e.term}
              </li>
            ))}
          </ul>
        </div>
      )}
      {scope.secondary.length > 0 && (
        <p className="text-xs text-muted">Also pointed to: {scope.secondary.map((n) => n.value).join(", ")}.</p>
      )}
    </div>
  );
}

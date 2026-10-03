import type { RiskSignal } from "../../api/types";
import { ago } from "../../lib/format";
import { relationNote } from "../../lib/provenance";
import { SourceBadge, Stat } from "../ui";

/** Corroboration, kept separate from the estimate: the model deliberately does not read how many outlets carried the story. */
export function Coverage({ s, asOf }: { s: RiskSignal; asOf: string }) {
  const e = s.evidence;
  const list = e.corroborating;
  const head = list.slice(0, 4);
  const rest = list.slice(4);
  const row = (c: (typeof list)[number]) => (
    <li key={c.url ?? c.headline} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm">
      <span className="min-w-0 flex-1 basis-56 text-ink-2">{c.headline}</span>
      <span className="flex items-center gap-3 text-xs">
        <span className="text-muted" title={c.relation}>
          {relationNote(c.relation)}
        </span>
        <SourceBadge type={c.source_type} name={c.source} />
        <span className="num text-muted">{ago(c.published_at, asOf)}</span>
      </span>
    </li>
  );
  return (
    <div className="coverage">
      <h3 className="mb-3 text-sm font-semibold">Coverage of this story</h3>
      <div className="grid grid-cols-3 gap-x-6 gap-y-4">
        <Stat label="Reports" value={e.source_count} sub={`${e.unique_domain_count} outlet${e.unique_domain_count === 1 ? "" : "s"}`} />
        <Stat label="Novelty" value={e.novelty_score.toFixed(2)} sub="0 repeat · 1 new" />
        <Stat label="Pace" value={`${e.coverage_velocity.toFixed(1)}/h`} sub="reports per hour" />
      </div>
      {list.length === 0 ? (
        <p className="mt-4 text-sm text-muted">No other source carried this story. Treat it as unconfirmed.</p>
      ) : (
        <>
          <ul className="mt-4 divide-y divide-rule border-y border-rule">{head.map(row)}</ul>
          {rest.length > 0 && (
            <details className="disclosure mt-2">
              <summary>Show {rest.length} more report{rest.length === 1 ? "" : "s"}</summary>
              <ul className="mt-2 divide-y divide-rule border-y border-rule">{rest.map(row)}</ul>
            </details>
          )}
        </>
      )}
      <p className="mt-3 text-xs text-muted">Outlet counts are context only. The impact model does not read them: coverage after the first report would be information from the future.</p>
    </div>
  );
}

import { Link } from "react-router-dom";
import { useWatchlistActivity } from "../../api/hooks";
import type { ItemActivity, MonitorMode, Watchlist, WatchedEvent } from "../../api/types";
import { LIFECYCLE_LABEL, NOVELTY_LABEL, STRENGTH_LABEL } from "../../lib/intelligence";
import { CHANGE_LABEL, pctPoints } from "../../lib/monitor";
import { KIND_LABEL } from "../../lib/watchlist";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { ErrorState, Skeleton, StatusTag } from "../ui";

function EventRow({ e }: { e: WatchedEvent }) {
  return (
    <li className="border-t border-rule py-3 first:border-t-0">
      <div className="flex flex-wrap items-center gap-2">
        {e.is_new && <StatusTag tone="ok">New</StatusTag>}
        {e.recent_changes.map((c) => <StatusTag key={c} tone="demo">{CHANGE_LABEL[c]}</StatusTag>)}
      </div>
      <Link to={`/events/${e.lead_signal_id}`} className="mt-1 block font-medium leading-snug text-ink hover:text-accent-strong">{e.headline}</Link>
      <p className="mt-1 text-xs text-muted">Why it is here: {e.match_reason}.</p>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
        {e.severity != null && <span>Severity {e.severity}/10</span>}
        {e.lifecycle && <span>{LIFECYCLE_LABEL[e.lifecycle] ?? e.lifecycle}</span>}
        {e.novelty && <span>Novelty: {NOVELTY_LABEL[e.novelty] ?? e.novelty}</span>}
        {e.velocity_per_hour != null && <span>{e.velocity_per_hour.toFixed(2)} sources/h</span>}
        <span>Evidence {STRENGTH_LABEL[e.evidence_tier] ?? e.evidence_tier}</span>
        {e.conflict !== "NO_CONFLICT" && <span className="text-warn">{e.conflict === "RESOLVED_CONFLICT" ? "Conflict resolved" : "Conflicting reports"}</span>}
        {e.materiality && <span>Relevance to the book: {e.materiality.toLowerCase()}{e.exposure_share != null ? ` (${(e.exposure_share * 100).toFixed(0)}% reached)` : ""}</span>}
        {e.stress_pnl_pct != null && <span className="inline-flex items-center gap-1.5"><KindBadge kind="scenario" /> {pctPoints(e.stress_pnl_pct)} of the book</span>}
      </p>
    </li>
  );
}

function Item({ a }: { a: ItemActivity }) {
  const r = a.rollup;
  return (
    <section className="card card-pad" aria-label={`${KIND_LABEL[a.item.kind]} ${a.item.label || a.item.value}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="font-display font-semibold">
          <span className="eyebrow mr-2">{KIND_LABEL[a.item.kind]}</span>
          {a.item.label || a.item.value}
        </h4>
        <span className="text-xs text-muted">
          {a.status === "MATCHED" ? `${a.matched_events} event${a.matched_events === 1 ? "" : "s"}${a.new_events ? ` · ${a.new_events} new` : ""}` : a.status === "DISABLED" ? "Switched off" : "No events"}
        </span>
      </div>
      {a.status !== "MATCHED" && <p className="mt-2 text-sm text-ink-2">{a.reason}</p>}
      {r && (
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {r.max_severity != null && <span>Highest severity {r.max_severity}/10</span>}
          {r.max_materiality && <span>Most relevant to the book: {r.max_materiality.toLowerCase()}</span>}
          {r.conflicts_open > 0 && <span>{r.conflicts_open} with conflicting reports</span>}
          {Object.entries(r.lifecycle_counts).length > 0 && <span>{Object.entries(r.lifecycle_counts).map(([k, n]) => `${n} ${(LIFECYCLE_LABEL[k] ?? k).toLowerCase()}`).join(", ")}</span>}
        </p>
      )}
      {a.events.length > 0 && <ul className="mt-2 list-none p-0" aria-label="Matching events">{a.events.map((e) => <EventRow key={e.event_id} e={e} />)}</ul>}
      {a.truncated && <p className="mt-2 text-xs text-muted">Showing the newest of {a.matched_events}; only the newest {a.scanned} were assessed.</p>}
    </section>
  );
}

/** What each item of a watchlist shows now, from the monitor's own event states: nothing is re-inferred here. */
export function WatchlistActivityView({ w, mode, cycle, window }: { w: Watchlist; mode: MonitorMode; cycle: number | null; window: number }) {
  const q = useWatchlistActivity(w.id, mode, cycle, window);
  if (q.isLoading) return <div className="space-y-3"><Skeleton className="h-5 w-1/2" /><Skeleton className="h-24 w-full" /></div>;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const a = q.data;
  if (!a) return null;
  if (a.status === "UNAVAILABLE") return <StateNotice tone="info" what="Activity is not available." why={a.reason ?? "The monitor cannot answer."} />;
  return (
    <div className="space-y-3">
      {a.status === "DISABLED" && <StateNotice tone="info" what="This watchlist is switched off." why="It is kept but matches nothing. Switch it on to see activity." />}
      {a.items.length === 0 && <p className="text-sm text-ink-2">This watchlist has no items yet.</p>}
      {a.items.map((i) => <Item key={`${i.item.kind}-${i.item.value}`} a={i} />)}
      <p className="text-xs text-muted">{a.labels[0]}</p>
    </div>
  );
}

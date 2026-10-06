import { useState } from "react";
import { useWatchlistMutations, useWatchlists } from "../../api/hooks";
import type { Watchlist } from "../../api/types";
import { KIND_LABEL } from "../../lib/watchlist";
import { useMonitorView } from "../monitor/ChangesFeed";
import { EmptyState, ErrorState, Loading, StatusTag } from "../ui";
import { Plus } from "../icons";
import { WatchlistActivityView } from "./WatchlistActivity";
import { WatchlistEditor } from "./WatchlistEditor";

function ListCard({ w, onEdit }: { w: Watchlist; onEdit: () => void }) {
  const m = useWatchlistMutations();
  const { mode, cycleParam } = useMonitorView();
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  return (
    <li className="card card-pad">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="font-display text-lg font-semibold leading-snug">{w.name}</h3>
          <p className="mt-1 flex flex-wrap gap-1.5" aria-label="Watched items">
            {w.items.length === 0 ? <span className="text-sm text-muted">No items</span> : w.items.map((i) => (
              <span key={`${i.kind}-${i.value}`} className="chip"><span className="text-muted">{KIND_LABEL[i.kind]}</span> {i.label || i.value}</span>
            ))}
          </p>
        </div>
        <div className="flex items-center gap-2">{w.enabled ? <StatusTag tone="ok">On</StatusTag> : <StatusTag tone="warn">Off</StatusTag>}</div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" className="btn btn-primary" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide activity" : "Inspect activity"}</button>
        <button type="button" className="btn" onClick={onEdit}>Edit</button>
        <button type="button" className="btn" onClick={() => m.update.mutate({ id: w.id, body: { name: w.name, enabled: !w.enabled, items: w.items.map((i) => ({ kind: i.kind, value: i.value, label: i.label })) } })}>
          {w.enabled ? "Switch off" : "Switch on"}
        </button>
        {confirm ? (
          <span className="flex items-center gap-2 text-sm">
            Delete “{w.name}”?
            <button type="button" className="btn" onClick={() => m.remove.mutate(w.id)}>Yes, delete</button>
            <button type="button" className="btn btn-ghost" onClick={() => setConfirm(false)}>Keep</button>
          </span>
        ) : (
          <button type="button" className="btn btn-ghost" onClick={() => setConfirm(true)}>Delete</button>
        )}
      </div>
      {(m.update.error || m.remove.error) && <div className="mt-3"><ErrorState error={(m.update.error ?? m.remove.error) as Error} /></div>}
      {open && <div className="mt-4 border-t border-rule pt-4"><WatchlistActivityView w={w} mode={mode} cycle={mode === "REPLAY" ? cycleParam : null} window={mode === "REPLAY" ? 6 : 1} /></div>}
    </li>
  );
}

/** Persistent watchlists: what to keep an eye on, and what the monitor shows about each item right now. */
export function WatchlistsPanel() {
  const q = useWatchlists();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  if (q.isLoading) return <Loading label="Loading watchlists" />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const lists = q.data?.watchlists ?? [];
  const current = typeof editing === "string" && editing !== "new" ? lists.find((l) => l.id === editing) : undefined;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-[64ch] text-sm text-ink-2">Watch companies, sectors, industries, regions, event types, risk themes or your own holdings. Each item shows the matching events and what changed, from the same monitor as the Risk Feed.</p>
        {editing === null && <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}><Plus size={14} /> New watchlist</button>}
      </div>
      {editing === "new" && <WatchlistEditor onDone={() => setEditing(null)} />}
      {current && <WatchlistEditor key={current.id} initial={current} onDone={() => setEditing(null)} />}
      {lists.length === 0 && editing === null && (
        <EmptyState title="No watchlists yet">Create one to follow a subject. A company matches only events whose company was resolved; unresolved events never match one.</EmptyState>
      )}
      <ul className="grid list-none gap-4 p-0" aria-label="Watchlists">
        {lists.map((w) => <ListCard key={w.id} w={w} onEdit={() => setEditing(w.id)} />)}
      </ul>
    </div>
  );
}

import { useState } from "react";
import { useMeta, useWatchlistMutations, useWatchlists } from "../../api/hooks";
import type { RiskSignal, WatchItemInput } from "../../api/types";
import { KIND_LABEL } from "../../lib/watchlist";

/** Add what this event is about to a watchlist. Only subjects EventShock resolved are offered: an unresolved event offers nothing to watch as a company. */
export function WatchButton({ s, eventType }: { s: RiskSignal; eventType?: string | null }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.watchlists === true;
  const lists = useWatchlists(on);
  const m = useWatchlistMutations();
  const [added, setAdded] = useState<string | null>(null);
  if (!on) return null;
  const options: WatchItemInput[] = [];
  if (s.scope.level === "COMPANY" && s.entity.entity_id !== "UNKNOWN_ENTITY") options.push({ kind: "COMPANY", value: s.entity.entity_id, label: `${s.entity.entity_name ?? s.entity.entity_id}` });
  if (s.scope.sector && (s.scope.level === "COMPANY" || s.scope.level === "SECTOR")) options.push({ kind: "SECTOR", value: s.scope.sector, label: s.scope.sector });
  if (eventType && eventType !== "NO_EVENT") options.push({ kind: "EVENT_TYPE", value: eventType, label: eventType.replace(/_/g, " ").toLowerCase() });
  if (options.length === 0) return <p className="text-xs text-muted">No resolved subject to watch for this event.</p>;

  const add = (item: WatchItemInput) => {
    const target = lists.data?.watchlists[0];
    const done = () => setAdded(`${KIND_LABEL[item.kind]}: ${item.label}`);
    if (target) {
      m.update.mutate({ id: target.id, body: { name: target.name, enabled: target.enabled, items: [...target.items.map((i) => ({ kind: i.kind, value: i.value, label: i.label })), item] } }, { onSuccess: done });
    } else {
      m.create.mutate({ name: "My watchlist", enabled: true, items: [item] }, { onSuccess: done });
    }
  };
  return (
    <details className="disclosure inline-block">
      <summary>Watch this</summary>
      <ul className="mt-2 list-none space-y-1.5 p-0">
        {options.map((o) => (
          <li key={`${o.kind}-${o.value}`}>
            <button type="button" className="btn btn-sm" onClick={() => add(o)} disabled={m.create.isPending || m.update.isPending}>Add {KIND_LABEL[o.kind].toLowerCase()}: {o.label}</button>
          </li>
        ))}
      </ul>
      {added && <p role="status" className="mt-2 text-xs text-ink-2">Added to your watchlist — {added}.</p>}
      {(m.create.error || m.update.error) && <p role="alert" className="mt-2 text-xs text-neg">{((m.create.error ?? m.update.error) as Error).message}</p>}
    </details>
  );
}

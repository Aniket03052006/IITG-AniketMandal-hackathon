import { useMemo, useState } from "react";
import { useWatchVocabulary, useWatchlistMutations } from "../../api/hooks";
import type { VocabEntry, WatchItemInput, WatchKind, Watchlist, WatchVocabulary } from "../../api/types";
import { KINDS, KIND_BLURB, KIND_LABEL } from "../../lib/watchlist";
import { ErrorState } from "../ui";

export function entriesFor(v: WatchVocabulary, kind: WatchKind): VocabEntry[] {
  switch (kind) {
    case "COMPANY": return v.companies;
    case "SECTOR": return v.sectors;
    case "INDUSTRY": return v.industries;
    case "GEOGRAPHY": return v.geographies;
    case "EVENT_TYPE": return v.event_types;
    case "RISK_THEME": return v.risk_themes;
    case "PORTFOLIO_EXPOSURE": return v.portfolio_exposure;
  }
}

/** Create or edit a watchlist. The pickers are the API's own vocabulary, so a subject that cannot be matched cannot be added: free text never becomes a company. */
export function WatchlistEditor({ initial, onDone }: { initial?: Watchlist; onDone: () => void }) {
  const vocab = useWatchVocabulary();
  const m = useWatchlistMutations();
  const [name, setName] = useState(initial?.name ?? "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [items, setItems] = useState<WatchItemInput[]>((initial?.items ?? []).map((i) => ({ kind: i.kind, value: i.value, label: i.label })));
  const [kind, setKind] = useState<WatchKind>("COMPANY");
  const [value, setValue] = useState("");
  const options = useMemo(() => (vocab.data ? entriesFor(vocab.data, kind) : []), [vocab.data, kind]);
  const err = (initial ? m.update.error : m.create.error) as Error | null;
  const pending = m.create.isPending || m.update.isPending;

  const add = () => {
    if (!value) return;
    if (items.some((i) => i.kind === kind && i.value.toLowerCase() === value.toLowerCase())) return;
    const label = options.find((o) => o.value === value)?.label ?? (value.startsWith("top:") ? `Top ${value.slice(4)} holdings` : value);
    setItems([...items, { kind, value, label }]);
    setValue("");
  };
  const save = () => {
    const body = { name: name.trim(), enabled, items };
    if (initial) m.update.mutate({ id: initial.id, body }, { onSuccess: onDone });
    else m.create.mutate(body, { onSuccess: onDone });
  };

  return (
    <form className="card card-pad space-y-4" onSubmit={(e) => { e.preventDefault(); save(); }} aria-label={initial ? "Edit watchlist" : "New watchlist"}>
      <div className="flex flex-wrap items-end gap-4">
        <label className="min-w-56 flex-1">
          <span className="eyebrow block">Name</span>
          <input className="field mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="e.g. Energy and rates" required />
        </label>
        <label className="flex items-center gap-2 pb-2 text-sm">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> Enabled
        </label>
      </div>

      <fieldset className="space-y-2">
        <legend className="eyebrow">Items</legend>
        {items.length === 0 && <p className="text-sm text-ink-2">Nothing watched yet. Add a company, a sector, an event type or a risk theme below.</p>}
        <ul className="flex flex-wrap gap-2 p-0" aria-label="Watched items">
          {items.map((i) => (
            <li key={`${i.kind}-${i.value}`} className="chip list-none" data-kind={i.kind}>
              <span className="text-muted">{KIND_LABEL[i.kind]}</span> {i.label || i.value}
              <button type="button" className="ml-2" aria-label={`Remove ${i.label || i.value}`} onClick={() => setItems(items.filter((x) => !(x.kind === i.kind && x.value === i.value)))}>×</button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-end gap-3 pt-1">
          <label>
            <span className="eyebrow block">Kind</span>
            <select className="field mt-1" value={kind} onChange={(e) => { setKind(e.target.value as WatchKind); setValue(""); }}>
              {KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
          </label>
          <label className="min-w-56 flex-1">
            <span className="eyebrow block">Subject</span>
            <select className="field mt-1 w-full" value={value} onChange={(e) => setValue(e.target.value)} disabled={!vocab.data}>
              <option value="">Choose…</option>
              {options.map((o) => <option key={o.value} value={o.value === "top:N" ? "top:3" : o.value}>{o.value === "top:N" ? "Top 3 holdings by value" : o.label}</option>)}
            </select>
          </label>
          <button type="button" className="btn" onClick={add} disabled={!value}>Add</button>
        </div>
        <p className="text-xs text-muted">{KIND_BLURB[kind]}</p>
      </fieldset>

      {err && <ErrorState error={err} />}
      <div className="flex items-center gap-2">
        <button type="submit" className="btn btn-primary" disabled={pending || !name.trim()}>{initial ? "Save changes" : "Create watchlist"}</button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>Cancel</button>
      </div>
    </form>
  );
}

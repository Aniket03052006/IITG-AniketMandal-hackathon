import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EventCategory, SignalSummary } from "../../api/types";
import { EVENT_CATEGORIES } from "../../api/types";
import { severityBand } from "../../lib/severity";
import { CategoryGlyph } from "../Glyph";
import { CATEGORY_ICON } from "../icons";

const time = (iso: string) => {
  const d = new Date(iso);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
};
const day = (iso: string) => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });

/** The score a row leads with: the assessment's severity where it exists, the impact model's otherwise. */
const scoreOf = (s: SignalSummary, assessed: boolean) => (assessed ? s.severity_score ?? null : s.impact_score);

/**
 * The incoming wire: market events newest first, each with its event-type glyph, a serif headline (what was reported) and its score.
 * Selecting one (click, or J / K) re-draws the trace beside it. Non-events stay in the full table below; the wire is for events.
 */
export function EventStream({
  items,
  selected,
  onSelect,
  label,
  assessed,
  total,
}: {
  items: SignalSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
  label: (c: string) => string;
  assessed: boolean;
  total: number;
}) {
  const [cat, setCat] = useState<EventCategory | null>(null);
  const [limit, setLimit] = useState(14);
  const listRef = useRef<HTMLOListElement>(null);

  const events = useMemo(
    () => items.filter((s) => s.event_status === "CLASSIFIED").sort((a, b) => b.published_at.localeCompare(a.published_at) || a.id.localeCompare(b.id)),
    [items],
  );
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of events) m.set(s.category, (m.get(s.category) ?? 0) + 1);
    return m;
  }, [events]);
  const shown = useMemo(() => {
    const pool = cat ? events.filter((s) => s.category === cat) : events;
    // the selected event always stays on the wire, even when it is older than the page
    const head = pool.slice(0, limit);
    const sel = pool.find((s) => s.id === selected);
    return sel && !head.includes(sel) ? [...head, sel] : head;
  }, [events, cat, limit, selected]);

  // keep the selected event in view inside the wire (scrolls the list, never the page)
  useEffect(() => {
    const list = listRef.current;
    const el = list?.querySelector<HTMLElement>(`[data-id="${selected}"]`);
    if (!list || !el) return;
    const top = el.offsetTop; // .wire-list is the offset parent (position: relative)
    if (top < list.scrollTop || top + el.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = Math.max(0, top - list.clientHeight / 3);
  }, [selected, shown.length]);

  // J / K move the selection along the wire (not while typing)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key !== "j" && e.key !== "k") return;
      const i = shown.findIndex((s) => s.id === selected);
      const next = shown[e.key === "j" ? Math.min(i + 1, shown.length - 1) : Math.max(i - 1, 0)];
      if (next && next.id !== selected) {
        e.preventDefault();
        onSelect(next.id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, selected, onSelect]);

  let lastDay = "";
  return (
    <aside className="wire" aria-label="Incoming wire">
      <div className="wire-head">
        <h2 className="font-sans text-md font-semibold">Incoming wire</h2>
        <span className="num text-xs text-muted">
          {events.length.toLocaleString("en-US")} events · {total.toLocaleString("en-US")} reports
        </span>
      </div>
      <div className="wire-filters" role="group" aria-label="Filter the wire by event type">
        <button type="button" className="chip" aria-pressed={cat === null} onClick={() => setCat(null)}>
          All
        </button>
        {EVENT_CATEGORIES.filter((c) => counts.has(c)).map((c) => {
          const I = CATEGORY_ICON[c];
          return (
            <button key={c} type="button" className="chip" aria-pressed={cat === c} onClick={() => setCat(cat === c ? null : c)} title={`${counts.get(c)} ${label(c)} events`}>
              {I && <I size={13} />}
              {label(c).split(" / ")[0]}
            </button>
          );
        })}
      </div>
      <ol ref={listRef} className="wire-list" aria-label="Market events, newest first">
        {shown.map((s) => {
          const sc = scoreOf(s, assessed);
          const b = sc != null ? severityBand(sc) : null;
          const d = day(s.published_at);
          const showDay = d !== lastDay;
          lastDay = d;
          const on = s.id === selected;
          return (
            <li key={s.id}>
              {showDay && <p className="wire-day num">{d}</p>}
              <button
                type="button"
                data-id={s.id}
                className={clsx("wire-item", on && "is-selected")}
                aria-pressed={on}
                aria-label={`${s.headline}${sc != null ? `, ${assessed ? "severity" : "impact"} ${sc}` : ""}`}
                onClick={() => onSelect(s.id)}
              >
                <span className="wire-time num">{time(s.published_at)}</span>
                <CategoryGlyph category={s.category as EventCategory} tone={on ? "accent" : "neutral"} />
                <span className="min-w-0">
                  <span className="wire-headline">{s.headline}</span>
                  <span className="wire-meta">
                    {sc != null && b && <span className={clsx("num font-semibold", b.text)}>{sc}</span>}
                    <span>{s.ticker ?? s.entity_name ?? s.scope_value ?? s.scope_sector ?? "market-wide"}</span>
                    <span aria-hidden="true">·</span>
                    <span>{label(s.category).split(" / ")[0]}</span>
                    {s.source_count > 1 && <span className="num">· {s.source_count} reports</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {(cat ? (counts.get(cat) ?? 0) : events.length) > limit && (
        <button type="button" className="btn btn-ghost mx-4 self-start" onClick={() => setLimit((l) => l + 20)}>
          Show older events
        </button>
      )}
      <p className="wire-foot">
        Select with a click or <kbd className="kbd">J</kbd> <kbd className="kbd">K</kbd>. The trace follows.
      </p>
    </aside>
  );
}

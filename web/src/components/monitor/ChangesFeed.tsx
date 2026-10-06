import clsx from "clsx";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMeta, useMonitorChanges, useMonitorCycles, useMonitorStatus } from "../../api/hooks";
import type { ChangeType, MonitorMode, RiskChange } from "../../api/types";
import { CHANGE_BLURB, CHANGE_LABEL, CHANGE_TONE, CHANGE_TYPES, pctPoints } from "../../lib/monitor";
import { when } from "../../lib/intelligence";
import { LIFECYCLE_LABEL, STRENGTH_LABEL } from "../../lib/intelligence";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { ErrorState, Skeleton, StatusTag } from "../ui";

/** The mode and the replay cycle live in the URL (`?mode=`, `?cycle=`), so a view can be shared and the replay is the same for everyone. */
export function useMonitorView() {
  const [sp, setSp] = useSearchParams();
  const mode: MonitorMode = sp.get("mode") === "LIVE" ? "LIVE" : "REPLAY";
  const raw = sp.get("cycle");
  const cycleParam = raw != null && /^\d+$/.test(raw) ? Number(raw) : null;
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) (v == null ? next.delete(k) : next.set(k, v));
    setSp(next, { replace: true });
  };
  return { mode, cycleParam, set };
}

function Evidence({ c }: { c: RiskChange }) {
  if (c.supporting_evidence.length === 0) return null;
  return (
    <details className="disclosure mt-2">
      <summary>Evidence ({c.supporting_evidence.length})</summary>
      <ul className="mt-2 space-y-1.5 text-sm">
        {c.supporting_evidence.map((e, i) => (
          <li key={`${e.kind}-${e.report_id ?? i}-${i}`}>
            <span className="eyebrow mr-2">{e.kind === "LIFECYCLE_TRANSITION" ? "Lifecycle cue" : e.kind === "CONFLICT" ? "Claim" : e.kind === "SCORE" ? "Score" : "Report"}</span>
            <span className="text-ink">“{e.text}”</span>
            <span className="ml-2 text-xs text-muted">
              {e.source ? `${e.source} · ` : ""}
              {e.at ? when(e.at) : ""}
              {e.rule ? ` · rule ${e.rule}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function ChangeRow({ c, showCycle }: { c: RiskChange; showCycle?: boolean }) {
  const s = c.current;
  const impact = c.portfolio_impact;
  return (
    <li className="border-b border-rule px-4 py-3.5" data-change-type={c.change_type}>
      <div className="flex flex-wrap items-center gap-2">
        <StatusTag tone={CHANGE_TONE[c.change_type]}>{CHANGE_LABEL[c.change_type]}</StatusTag>
        <span className="text-xs text-muted">{when(c.at)}{showCycle && c.cycle != null ? ` · cycle ${c.cycle}` : ""}</span>
      </div>
      <Link to={`/events/${s.lead_signal_id}`} className="mt-1.5 block font-medium leading-snug text-ink hover:text-accent-strong">
        {c.headline}
      </Link>
      <p className="mt-1 text-sm text-ink-2">{c.summary}</p>
      <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        {s.severity != null && <span>Severity {s.severity}/10</span>}
        {s.lifecycle && <span>{LIFECYCLE_LABEL[s.lifecycle] ?? s.lifecycle}</span>}
        <span>Evidence {STRENGTH_LABEL[s.evidence_tier] ?? s.evidence_tier}</span>
        <span>{s.independent_sources} independent source{s.independent_sources === 1 ? "" : "s"}</span>
        {impact?.materiality_current && <span>Relevance to the book: {impact.materiality_current.toLowerCase()}</span>}
        {c.change_type === "STRESS_CHANGED" && impact && (
          <span className="inline-flex items-center gap-1.5">
            <KindBadge kind="scenario" /> {pctPoints(impact.stress_pnl_pct_previous)} → {pctPoints(impact.stress_pnl_pct_current)} of the book
          </span>
        )}
        <span title={CHANGE_BLURB[c.change_type]}>Rule: {c.rule}</span>
      </p>
      <Evidence c={c} />
    </li>
  );
}

/** What changed recently. REPLAY steps a fixed clock over the frozen signals (the same answer every time, no internet needed); LIVE reads the change log the live feed produces. */
export function ChangesFeed({ limit, heading = "What changed recently", showControls = true }: { limit?: number; heading?: string; showControls?: boolean }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.monitor === true;
  const { mode, cycleParam, set } = useMonitorView();
  const status = useMonitorStatus(mode, on);
  const cycles = useMonitorCycles(on && mode === "REPLAY");
  const last = (cycles.data?.length ?? 1) - 1;
  const cycle = mode === "REPLAY" ? (cycleParam != null ? Math.min(cycleParam, Math.max(last, 0)) : last) : null;
  const ready = on && (mode === "LIVE" || cycles.isSuccess);
  const changes = useMonitorChanges(mode, cycle, 1, ready);
  const [types, setTypes] = useState<ReadonlySet<ChangeType>>(new Set());
  const [all, setAll] = useState(false);

  const rows = useMemo(() => (changes.data?.changes ?? []).filter((c) => types.size === 0 || types.has(c.change_type)), [changes.data, types]);
  if (!on) return null;
  const shown = limit && !all ? rows.slice(0, limit) : rows;
  const cur = cycle != null ? cycles.data?.[cycle] : undefined;
  const present = CHANGE_TYPES.filter((t) => (changes.data?.counts?.[t] ?? 0) > 0);
  const toggle = (t: ChangeType) => setTypes((p) => { const n = new Set(p); (n.has(t) ? n.delete(t) : n.add(t)); return n; });

  return (
    <section aria-labelledby="changes-title" className="card">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-rule px-4 py-3.5">
        <div className="min-w-0">
          <p className="eyebrow">Monitor</p>
          <h2 id="changes-title" className="font-display text-lg font-semibold">{heading}</h2>
          <p className="mt-0.5 text-sm text-muted">Changes in how EventShock assesses each event. An article about an existing event updates that event; it is never a new risk.</p>
        </div>
        {showControls && (
          <div role="group" aria-label="Monitor mode" className="flex items-center gap-2">
            <button type="button" className="chip" aria-pressed={mode === "REPLAY"} onClick={() => set({ mode: null, cycle: null })}>Replay · deterministic</button>
            <button type="button" className="chip" aria-pressed={mode === "LIVE"} onClick={() => set({ mode: "LIVE", cycle: null })}>Live</button>
          </div>
        )}
      </div>

      {mode === "REPLAY" && showControls && cycles.data && cycles.data.length > 1 && cycle != null && (
        <div className="tl-controls flex flex-wrap items-center gap-3 border-b border-rule px-4 py-3">
          <span className="eyebrow">Replay clock</span>
          <button type="button" className="btn btn-sm" disabled={cycle <= 1} onClick={() => set({ cycle: String(cycle - 1) })} aria-label="Previous cycle">‹</button>
          <input type="range" aria-label="Replay cycle" min={1} max={last} value={Math.max(cycle, 1)} onChange={(e) => set({ cycle: e.target.value })} className="min-w-40 flex-1" />
          <button type="button" className="btn btn-sm" disabled={cycle >= last} onClick={() => set({ cycle: String(cycle + 1) })} aria-label="Next cycle">›</button>
          <output className="num text-sm text-ink-2">Cycle {cycle} of {last} · {cur ? when(cur.at) : ""}</output>
        </div>
      )}

      <div className="px-0">
        {(status.isLoading || changes.isLoading || (mode === "REPLAY" && cycles.isLoading)) && <div className="space-y-3 px-4 py-4"><Skeleton className="h-5 w-2/3" /><Skeleton className="h-16 w-full" /></div>}
        {status.data && !status.data.available && (
          <div className="p-4">
            <StateNotice tone="info" what={mode === "LIVE" ? "The live feed is not running." : "The replay clock is not available."} why={status.data.reason ?? "No monitor is available."}
              next={mode === "LIVE" ? <button type="button" className="btn btn-sm" onClick={() => set({ mode: null, cycle: null })}>Show the replay instead</button> : undefined} />
          </div>
        )}
        {changes.error && !(status.data && !status.data.available) && <div className="p-4"><ErrorState error={changes.error} retry={() => changes.refetch()} /></div>}
        {changes.data && status.data?.available !== false && (
          <>
            {present.length > 1 && (
              <div className="flex flex-wrap items-center gap-1.5 border-b border-rule px-4 py-2.5" role="group" aria-label="Filter by type of change">
                {present.map((t) => (
                  <button key={t} type="button" className="chip" aria-pressed={types.has(t)} onClick={() => toggle(t)}>
                    {CHANGE_LABEL[t]} <span className="num ml-1 text-muted">{changes.data?.counts?.[t]}</span>
                  </button>
                ))}
              </div>
            )}
            {shown.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-2">
                {types.size ? "No change of that type in this cycle." : mode === "REPLAY" ? "Nothing changed in this cycle: no tracked event crossed a threshold. Move the replay clock to see other cycles." : "No change has been logged yet."}
              </p>
            ) : (
              <ul aria-label="Changes" className={clsx("m-0 list-none p-0")}>
                {shown.map((c) => <ChangeRow key={c.change_id} c={c} showCycle={mode === "REPLAY"} />)}
              </ul>
            )}
            {limit && rows.length > limit && !all && (
              <div className="px-4 py-3"><button type="button" className="btn btn-sm" onClick={() => setAll(true)}>Show all {rows.length}</button></div>
            )}
            <p className="border-t border-rule px-4 py-2.5 text-xs text-muted">
              {changes.data.tracked_events} tracked event{changes.data.tracked_events === 1 ? "" : "s"}; {changes.data.untracked_events} below the tracking floor (counted, not listed)
              {changes.data.excluded_untrusted_clock > 0 ? `; ${changes.data.excluded_untrusted_clock} with replay-assigned times never placed on a timeline` : ""}. {changes.data.limitations[0]}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

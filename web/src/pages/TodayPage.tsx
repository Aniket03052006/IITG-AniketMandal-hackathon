import { useState } from "react";
import { useMeta, useMonitorCycles, useMonitorStatus, useDigest } from "../api/hooks";
import { DigestCardView } from "../components/digest/DigestCard";
import { StoryChain } from "../components/digest/StoryChain";
import { WhyDrawers } from "../components/explain/WhyDrawer";
import { ChangesFeed, useMonitorView } from "../components/monitor/ChangesFeed";
import { ReplayClock } from "../components/monitor/ReplayClock";
import { StateNotice } from "../components/StateNotice";
import { ErrorState, PageHeader, Skeleton } from "../components/ui";
import { SECTION_BLURB } from "../lib/digest";
import { when } from "../lib/intelligence";
import { useSearchParams } from "react-router-dom";

/** What should I care about right now? One ranked, explainable view of what changed, with every card drillable from the event to the attribution of its stress. */
export function TodayPage() {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.monitor === true;
  const { mode, cycleParam, set } = useMonitorView();
  const [params] = useSearchParams();
  const cycles = useMonitorCycles(on && mode === "REPLAY");
  const status = useMonitorStatus(mode, on);
  const last = (cycles.data?.length ?? 1) - 1;
  const cycle = mode === "REPLAY" ? (cycleParam != null ? Math.min(cycleParam, Math.max(last, 0)) : last) : null;
  const ready = on && (mode === "LIVE" || cycles.isSuccess);
  const digest = useDigest(mode, cycle, 4, ready);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  if (meta && !on) return <StateNotice what="Today is not available here." why="The risk monitor runs in the replay profile." />;
  const d = digest.data;
  const explain = meta?.capabilities.explanations === true;

  return (
    <>
      <PageHeader
        title="What should I care about right now?"
        sub="The changes that matter most to your portfolio, ordered by a documented key (never a score), each one explainable and drillable from the event to the attribution of its stress."
        actions={
          <div role="group" aria-label="Monitor mode" className="flex items-center gap-2">
            <button type="button" className="chip" aria-pressed={mode === "REPLAY"} onClick={() => set({ mode: null, cycle: null })}>Replay · deterministic</button>
            <button type="button" className="chip" aria-pressed={mode === "LIVE"} onClick={() => set({ mode: "LIVE", cycle: null })}>Live</button>
          </div>
        }
      />
      {mode === "REPLAY" && cycles.data && cycle != null && <div className="mb-5 rounded-md border border-rule p-3"><ReplayClock cycles={cycles.data} cycle={cycle} onChange={(c) => set({ cycle: String(c) })} /></div>}
      {status.data && !status.data.available && (
        <div className="mb-5">
          <StateNotice tone="info" what={mode === "LIVE" ? "The live feed is not running." : "The replay clock is not available."} why={status.data.reason ?? "No monitor is available."}
            next={mode === "LIVE" ? <button type="button" className="btn btn-sm" onClick={() => set({ mode: null, cycle: null })}>Show the replay instead</button> : undefined} />
        </div>
      )}
      {digest.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-40 w-full" /></div>}
      {digest.error && <ErrorState error={digest.error} retry={() => digest.refetch()} />}
      {d && d.availability === "UNAVAILABLE" && <StateNotice tone="info" what="Nothing to show yet." why={d.reason ?? "The digest is not available."} />}
      {d && d.availability === "AVAILABLE" && (
        <div className="space-y-6">
          <p className="text-sm text-muted">
            {d.tracked_events} tracked event{d.tracked_events === 1 ? "" : "s"}, {d.change_count} change{d.change_count === 1 ? "" : "s"} in the last {d.window} cycle{d.window === 1 ? "" : "s"}
            {d.as_of ? ` up to ${when(d.as_of)}` : ""}{d.portfolio_name ? ` · portfolio: ${d.portfolio_name}` : ""}. {d.ranking}
          </p>
          {d.sections.map((s) => {
            const open = expanded[s.id] ?? false;
            const cards = open ? s.cards : s.cards.slice(0, 3);
            return (
              <section key={s.id} aria-labelledby={`sec-${s.id}`} className="card">
                <div className="border-b border-rule px-4 py-3.5">
                  <h2 id={`sec-${s.id}`} className="font-display text-lg font-semibold">{s.title} <span className="num ml-1 text-sm font-normal text-muted">{s.total}</span></h2>
                  <p className="mt-0.5 text-sm text-muted">{SECTION_BLURB[s.id] ?? s.blurb}</p>
                </div>
                {s.cards.length === 0 ? (
                  <p className="px-4 py-5 text-sm text-ink-2">{s.id === "CONCENTRATION" ? "No new concentration in this window." : s.id === "WATCHLISTS" ? "Nothing on your watchlists changed in this window. Create a watchlist on the Portfolios page." : "Nothing in this section for this window."}</p>
                ) : (
                  <ul aria-label={s.title} className="m-0 list-none p-0">{cards.map((c) => <DigestCardView key={`${s.id}-${c.event_id ?? c.watch?.watchlist_id ?? c.overlap?.risk_factor}`} c={c} mode={mode} cycle={cycle} explain={explain} />)}</ul>
                )}
                {s.cards.length > 3 && <div className="px-4 py-3"><button type="button" className="btn btn-sm" onClick={() => setExpanded({ ...expanded, [s.id]: !open })}>{open ? "Show fewer" : `Show all ${s.cards.length}`}</button>{s.truncated && <span className="ml-3 text-xs text-muted">the top {s.cards.length} of {s.total}</span>}</div>}
              </section>
            );
          })}
          <ChangesFeed limit={6} heading="Every change in this view" showControls={false} />
          <StoryChain />
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}
      <WhyDrawers eventId={params.get("event") ?? undefined} subjects={["PRIORITY"]} cycle={cycle} />
    </>
  );
}

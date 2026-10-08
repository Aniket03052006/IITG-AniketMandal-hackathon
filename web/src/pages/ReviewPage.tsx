import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMeta, useReviewQueue } from "../api/hooks";
import { ReviewCard } from "../components/review/ReviewCard";
import { StateNotice } from "../components/StateNotice";
import { ErrorState, PageHeader, Skeleton } from "../components/ui";
import { getAnalyst, setAnalyst } from "../lib/analyst";
import { dateTime } from "../lib/format";
import { STATUS_TABS } from "../lib/review";

const COUNT_KEY = { OPEN: "open", REVIEWED: "reviewed", DISMISSED: "dismissed", ALL: "in_queue" } as const;

/** Events a person should look at. Each one carries the named rule(s) that queued it, the values that fired them and the order key; a decision here is a note, never ground truth, and it changes nothing that is served. */
export function ReviewPage() {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.review === true;
  const [params, setParams] = useSearchParams();
  const mode = params.get("mode") === "LIVE" ? "LIVE" : "REPLAY";
  const status = (STATUS_TABS.find((t) => t.id === params.get("status"))?.id ?? "OPEN") as (typeof STATUS_TABS)[number]["id"];
  const q = useReviewQueue(mode, status, on);
  const [analyst, setName] = useState(getAnalyst);
  const set = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) (v ? p.set(k, v) : p.delete(k));
    setParams(p, { replace: true });
  };
  if (meta && !on) return <StateNotice what="The review queue is not available here." why="It runs in the replay profile." />;
  const d = q.data;
  return (
    <>
      <PageHeader
        title="Review queue"
        sub="Events a person should look at, each with the named rule that queued it. Ordered by a key shown on every item (never a score). A decision is a note: it does not change a model, a score or anything served."
        actions={
          <div role="group" aria-label="Queue mode" className="flex items-center gap-2">
            <button type="button" className="chip" aria-pressed={mode === "REPLAY"} onClick={() => set({ mode: null })}>Replay · deterministic</button>
            <button type="button" className="chip" aria-pressed={mode === "LIVE"} onClick={() => set({ mode: "LIVE" })}>Live</button>
          </div>
        }
      />
      <div className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div role="group" aria-label="Show" className="flex flex-wrap items-center gap-2">
          {STATUS_TABS.map((t) => (
            <button key={t.id} type="button" className="chip" aria-pressed={status === t.id} onClick={() => set({ status: t.id === "OPEN" ? null : t.id })}>
              {t.label}
              {d ? <span className="num ml-1.5 text-muted">{d.counts[COUNT_KEY[t.id]]}</span> : null}
            </button>
          ))}
        </div>
        <div>
          <label htmlFor="reviewer" className="text-xs text-muted">Your name on decisions (kept in this browser)</label>
          <input id="reviewer" className="field mt-1 block w-56" value={analyst} maxLength={40} placeholder="anonymous" onChange={(e) => { setName(e.target.value); setAnalyst(e.target.value); }} />
        </div>
      </div>
      {q.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-1/3" /><Skeleton className="h-40 w-full" /></div>}
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {d && d.availability === "UNAVAILABLE" && (
        <StateNotice tone="info" what="Nothing to show yet." why={d.reason ?? "The queue is not available."}
          next={mode === "LIVE" ? <button type="button" className="btn btn-sm" onClick={() => set({ mode: null })}>Show the replay instead</button> : undefined} />
      )}
      {d && d.availability === "AVAILABLE" && (
        <div className="space-y-5">
          <p className="text-sm text-muted">
            {d.counts.in_queue} of {d.counts.tracked_events} tracked events need a look ({d.counts.open} open){d.as_of ? ` as of ${dateTime(d.as_of)}` : ""}. {d.ranking}
          </p>
          <section className="card" aria-label="Review queue">
            {d.items.length === 0 ? (
              <p className="px-4 py-6 text-sm text-ink-2">
                {status === "OPEN" ? "Nothing is waiting for review." : status === "ALL" ? "No event is in the queue." : `Nothing is ${status.toLowerCase()} yet.`}
              </p>
            ) : (
              <ul className="m-0 list-none p-0">{d.items.map((i, n) => <ReviewCard key={i.event_id} item={i} rank={n + 1} mode={mode} />)}</ul>
            )}
            {d.matching > d.items.length && <p className="px-4 py-3 text-xs text-muted">The first {d.items.length} of {d.matching}; the order puts the most material first.</p>}
          </section>
          <details className="disclosure">
            <summary>Why events are queued: the rules</summary>
            <dl className="mt-3 grid gap-3 text-sm">
              {d.rules.map((r) => (
                <div key={r.code}>
                  <dt className="font-medium">{r.label}</dt>
                  <dd className="text-muted">{r.rule}</dd>
                </div>
              ))}
            </dl>
          </details>
          <ul className="list-disc space-y-1 pl-5 text-xs text-muted">{d.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </div>
      )}
    </>
  );
}

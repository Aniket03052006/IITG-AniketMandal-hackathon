import { useState } from "react";
import { Link } from "react-router-dom";
import { useReviewDecide } from "../../api/hooks";
import type { ReviewItem, ReviewStatus } from "../../api/types";
import { getAnalyst } from "../../lib/analyst";
import { drillTo } from "../../lib/digest";
import { dateTime } from "../../lib/format";
import { factsLine, reasonTone, STATUS_LABEL } from "../../lib/review";
import { StatusTag } from "../ui";

/** One event waiting for a person: why it is here (the named rules, with the values that fired them), what it is, and the decision. A decision is a note: it moves the event between lists and nothing else. */
export function ReviewCard({ item, rank, mode }: { item: ReviewItem; rank: number; mode: "REPLAY" | "LIVE" }) {
  const decide = useReviewDecide();
  const [note, setNote] = useState("");
  const d = item.decision;
  const done = item.status !== "OPEN";
  const send = (status: ReviewStatus) =>
    decide.mutate({ event_id: item.event_id, status, note: note.trim() || null, analyst_id: getAnalyst().trim() || null }, { onSuccess: () => setNote("") });
  const noteId = `note-${item.event_id}`;
  return (
    <li className="border-b border-rule px-4 py-4" data-status={item.status} aria-label={item.headline}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="num text-xs text-muted" aria-label={`Position ${rank}`}>#{rank}</span>
        {done && <StatusTag tone={item.status === "REVIEWED" ? "ok" : "demo"}>{STATUS_LABEL[item.status]}</StatusTag>}
        {item.reasons.map((r) => (
          <span key={r.code} title={r.detail}>
            <StatusTag tone={reasonTone(r.code)}>{r.label}</StatusTag>
          </span>
        ))}
      </div>
      <Link to={drillTo({ step: "EVENT", signal_id: item.signal_id }, mode, null)} className="mt-1.5 block font-medium leading-snug text-ink hover:text-accent-strong">{item.headline}</Link>
      <p className="mt-1 text-sm text-ink-2">{factsLine(item)}</p>
      <ul className="mt-2 grid gap-1 text-sm text-muted" aria-label="Why it is in the queue">
        {item.reasons.map((r) => <li key={r.code}><span className="font-medium text-ink-2">{r.label}:</span> {r.detail}</li>)}
      </ul>
      <details className="disclosure mt-2">
        <summary>Why this position?</summary>
        <p className="mt-2 text-xs text-muted">Ordered by, in turn:</p>
        <ol className="mt-1 list-decimal pl-5 text-xs text-ink-2">
          {item.rank_key.map((p) => <li key={p.name}>{p.name}: <span className="num">{p.value}</span></li>)}
        </ol>
      </details>

      {item.changed_since_review && d && (
        <p className="mt-3 rounded-md border border-rule bg-warn-dim px-3 py-2 text-sm text-ink" role="status">
          Open again: it was {STATUS_LABEL[d.status].toLowerCase()} by {d.analyst_id} on {dateTime(d.created_at)} and its evidence has changed since.
          {d.note ? <> Your earlier note: <q>{d.note}</q></> : null}
        </p>
      )}
      {done && d && (
        <p className="mt-3 text-sm text-ink-2" role="status">
          {STATUS_LABEL[d.status]} by <span className="font-medium">{d.analyst_id}</span> on {dateTime(d.created_at)}.
          {d.note ? <> <q>{d.note}</q></> : null}
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-end gap-2">
        {!done && (
          <div className="min-w-[14rem] flex-1">
            <label htmlFor={noteId} className="text-xs text-muted">Note (optional)</label>
            <input id={noteId} className="field mt-1 w-full" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="what you checked, or why it is noise" disabled={decide.isPending} />
          </div>
        )}
        {!done && (
          <>
            <button type="button" className="btn btn-sm btn-primary" disabled={decide.isPending} onClick={() => send("REVIEWED")}>Mark reviewed</button>
            <button type="button" className="btn btn-sm" disabled={decide.isPending} onClick={() => send("DISMISSED")}>Dismiss</button>
          </>
        )}
        {done && <button type="button" className="btn btn-sm" disabled={decide.isPending} onClick={() => send("OPEN")}>Reopen</button>}
        {decide.isError && <span className="text-sm text-neg" role="alert">Not saved: {decide.error.message}</span>}
      </div>
    </li>
  );
}

import { Link } from "react-router-dom";
import type { DigestCard as Card } from "../../api/types";
import { CHANGE_LABEL, pctPoints } from "../../lib/monitor";
import { DRILL_LABEL, drillTo } from "../../lib/digest";
import { LIFECYCLE_LABEL, STRENGTH_LABEL } from "../../lib/intelligence";
import { KindBadge } from "../ProvenanceKind";
import { StatusTag } from "../ui";
import { useSearchParams } from "react-router-dom";
import { Question } from "../icons";
import { FeedbackBar } from "../feedback/FeedbackBar";

/** One card of the digest. Its position is explained by the key shown below it (not a score), and it drills down from the event to the attribution of its stress. */
export function DigestCardView({ c, mode, cycle, explain }: { c: Card; mode: "REPLAY" | "LIVE"; cycle: number | null; explain: boolean }) {
  const [params, setParams] = useSearchParams();
  const why = () => {
    const next = new URLSearchParams(params);
    if (c.event_id) next.set("event", c.event_id);
    next.set("open", "why-priority");
    setParams(next, { replace: true, preventScrollReset: true });
  };
  return (
    <li className="border-b border-rule px-4 py-4" data-kind={c.kind} data-rank={c.rank}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="num text-xs text-muted" aria-label={`Rank ${c.rank}`}>#{c.rank}</span>
        {c.change_types.map((t) => <StatusTag key={t} tone={t === "EVENT_ESCALATED" ? "neg" : "demo"}>{CHANGE_LABEL[t]}</StatusTag>)}
        {c.overlap && <StatusTag tone="warn">{c.overlap.status === "NEW" ? "New overlap" : "Overlap grew"}</StatusTag>}
      </div>
      {c.signal_id ? <Link to={drillTo({ step: "EVENT", signal_id: c.signal_id }, mode, cycle)} className="mt-1.5 block font-medium leading-snug text-ink hover:text-accent-strong">{c.headline}</Link> : <p className="mt-1.5 font-medium leading-snug text-ink">{c.headline}</p>}
      <p className="mt-1 text-sm text-ink-2">{c.summary}</p>
      {c.kind === "EVENT" && (
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {c.severity != null && <span>Severity {c.severity}/10</span>}
          {c.lifecycle && <span>{LIFECYCLE_LABEL[c.lifecycle] ?? c.lifecycle}</span>}
          {c.evidence_tier && <span>Evidence {STRENGTH_LABEL[c.evidence_tier] ?? c.evidence_tier}</span>}
          {c.materiality && <span>Relevance to the book: {c.materiality.toLowerCase()}{c.exposure_share != null ? ` (${(c.exposure_share * 100).toFixed(0)}% reached)` : ""}</span>}
          {c.stress_pnl_pct != null && <span className="inline-flex items-center gap-1.5"><KindBadge kind="scenario" /> {pctPoints(c.stress_pnl_pct)} of the book</span>}
        </p>
      )}
      {c.watch && c.watch.top.length > 0 && (
        <ul className="mt-2 list-none space-y-1 p-0 text-sm" aria-label="Top watched events">
          {c.watch.top.map((t) => <li key={String(t.signal_id)}><Link className="text-ink hover:text-accent-strong" to={drillTo({ step: "EVENT", signal_id: String(t.signal_id) }, mode, cycle)}>{String(t.headline)}</Link></li>)}
        </ul>
      )}
      <details className="disclosure mt-2">
        <summary>Why is this here, in this order?</summary>
        <dl className="mt-2 grid grid-cols-[minmax(0,10rem)_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs" aria-label="Ranking key">
          {c.rank_key.map((p) => (<div key={p.name} className="contents"><dt className="text-muted">{p.name}</dt><dd className="num text-ink-2">{p.value}</dd></div>))}
        </dl>
        <p className="mt-2 text-xs text-muted">Ordered by these components, left to right: not a score.</p>
        {explain && c.event_id && <button type="button" className="btn btn-sm mt-2" aria-haspopup="dialog" onClick={why}><Question size={14} /> Full reasons</button>}
      </details>
      {c.signal_id && explain && <div className="mt-2"><Link className="btn btn-sm" to={`${drillTo({ step: "EVENT", signal_id: c.signal_id }, mode, cycle)}${cycle != null && mode === "REPLAY" ? "&" : "?"}open=brief`}>Executive brief</Link></div>}
      {c.event_id && <div className="mt-2"><FeedbackBar eventId={c.event_id} cycle={cycle} /></div>}
      {c.drill.length > 0 && (
        <nav className="mt-2 flex flex-wrap items-center gap-x-1 gap-y-1 text-xs" aria-label="Drill down">
          {c.drill.map((d, i) => (
            <span key={d.step} className="inline-flex items-center gap-1">
              {i > 0 && <span aria-hidden="true" className="text-faint">→</span>}
              <Link className="text-ink-2 underline-offset-2 hover:text-ink hover:underline" to={drillTo(d, mode, cycle)}>{DRILL_LABEL[d.step] ?? d.step}</Link>
            </span>
          ))}
        </nav>
      )}
    </li>
  );
}

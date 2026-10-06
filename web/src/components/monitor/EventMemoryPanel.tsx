import { useEventTimeline, useMeta } from "../../api/hooks";
import type { EventMemory, MemoryItem } from "../../api/types";
import { LIFECYCLE_LABEL, STRENGTH_LABEL, when } from "../../lib/intelligence";
import { OBSERVATION_KIND, OBSERVATION_LABEL, UPDATE_LABEL, UPDATE_TONE, itemKey, pctPoints } from "../../lib/monitor";
import { Chapter } from "../event/Chapter";
import { KindBadge } from "../ProvenanceKind";
import { StateNotice } from "../StateNotice";
import { Skeleton, StatusTag } from "../ui";

function Item({ i }: { i: MemoryItem }) {
  const kind = OBSERVATION_KIND[i.observation] ?? null;
  return (
    <li className="tl-item">
      <span className="tl-node tl-node-known" aria-hidden="true" />
      <div className="min-w-0">
        <p className="tl-time num">{when(i.at)}</p>
        <p className="tl-title flex flex-wrap items-center gap-2">
          {i.update_kind && <StatusTag tone={UPDATE_TONE[i.update_kind] ?? "demo"}>{UPDATE_LABEL[i.update_kind] ?? i.update_kind}</StatusTag>}
          <span>{i.label}</span>
        </p>
        <p className="tl-sub">{i.detail}</p>
        <p className="tl-sub flex flex-wrap items-center gap-x-2 gap-y-1">
          {kind ? <KindBadge kind={kind} label={OBSERVATION_LABEL[i.observation]} /> : <span className="eyebrow">{OBSERVATION_LABEL[i.observation] ?? i.observation}</span>}
          {i.source && <span>{i.source}{i.independent === false ? " · copy" : i.independent ? " · independent" : ""}</span>}
          {i.rule && <span>Rule: {i.rule}</span>}
        </p>
      </div>
    </li>
  );
}

export function EventMemoryView({ m }: { m: EventMemory }) {
  if (m.availability === "UNAVAILABLE") {
    return <StateNotice tone="info" what="This event's history cannot be followed." why={m.reason ?? "Its report times were assigned by the replay."} />;
  }
  const counts = Object.entries(m.update_counts);
  return (
    <>
      <p className="mb-3 max-w-[72ch] text-sm text-ink-2">
        One event, {m.signal_ids.length} report cluster{m.signal_ids.length === 1 ? "" : "s"}. Each report is classified against the ones before it by an explicit rule; a copy or more of the same coverage is a continuation, not a new risk.
      </p>
      {counts.length > 0 && (
        <p className="mb-3 flex flex-wrap items-center gap-2" aria-label="How the reports were classified">
          {counts.map(([k, n]) => <StatusTag key={k} tone={UPDATE_TONE[k] ?? "demo"}>{UPDATE_LABEL[k] ?? k} · {n}</StatusTag>)}
        </p>
      )}
      <ol className="tl-track" aria-label="Event timeline">
        {m.items.map((i, n) => <Item key={itemKey(i, n)} i={i} />)}
      </ol>
      {m.history.length > 1 && (
        <details className="disclosure mt-4">
          <summary>History by monitoring cycle ({m.history.length})</summary>
          <div className="scroll-x mt-3">
            <table className="dtable">
              <caption className="sr-only">The event's state at each monitoring cycle</caption>
              <thead>
                <tr>
                  <th scope="col">As of</th><th scope="col">Severity</th><th scope="col">Lifecycle</th><th scope="col">Evidence</th><th scope="col">Relevance</th>
                  <th scope="col">Reach</th><th scope="col">Scenario P&amp;L <KindBadge kind="scenario" /></th>
                </tr>
              </thead>
              <tbody>
                {m.history.map((h) => (
                  <tr key={`${h.cycle}-${h.at}`}>
                    <td className="num">{when(h.at)}</td>
                    <td className="num">{h.severity ?? "–"}</td>
                    <td>{h.lifecycle ? LIFECYCLE_LABEL[h.lifecycle] ?? h.lifecycle : "–"}</td>
                    <td>{STRENGTH_LABEL[h.evidence_tier] ?? h.evidence_tier}</td>
                    <td>{h.materiality ?? "–"}</td>
                    <td className="num">{h.exposure_share != null ? `${(h.exposure_share * 100).toFixed(1)}%` : "–"}</td>
                    <td className="num">{pctPoints(h.stress_pnl_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <p className="mt-3 max-w-[72ch] text-xs text-muted">{m.limitations[0]}</p>
    </>
  );
}

/** The event as an evolving narrative: how it began, what each later report did to it, and how EventShock's assessment moved. */
export function EventMemoryPanel({ signalId }: { signalId: string }) {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.monitor === true;
  const q = useEventTimeline(signalId, on);
  if (!on) return null;
  return (
    <Chapter id="memory" eyebrow="Memory" title="How this event developed" lede="The event as an evolving narrative: new, continued, updated, escalated or resolved.">
      {q.isLoading && <Skeleton className="h-40 w-full" />}
      {q.data && <EventMemoryView m={q.data} />}
      {q.error && q.error.message && !q.error.message.includes("not found") && <p className="text-sm text-ink-2">The timeline could not be loaded: {q.error.message}</p>}
    </Chapter>
  );
}

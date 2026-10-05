import type { LifecycleView } from "../../api/types";
import { LIFECYCLE_BLURB, LIFECYCLE_LABEL, when } from "../../lib/intelligence";

/** Where the event is in its life and how it got there: each step names the rule and the report that caused it. */
export function LifecycleTimeline({ life }: { life: LifecycleView }) {
  if (life.availability !== "AVAILABLE" || life.state == null) {
    return <p className="text-sm text-ink-2">{life.reason ?? "The event's life cannot be followed."}</p>;
  }
  return (
    <div>
      <p className="tl-state">
        <span className="font-medium text-ink">{LIFECYCLE_LABEL[life.state]}</span> since {when(life.since)}. {LIFECYCLE_BLURB[life.state]}
        <span className="mt-1 block text-xs text-muted">
          State as of {when(life.as_of)} ({life.as_of_basis === "LAST_REPORT" ? "the event's last report, not the end of the data" : life.as_of_basis === "NOW" ? "now" : "the time you asked for"}).
        </span>
      </p>
      <ol className="tl-track" aria-label="Lifecycle transitions in time order">
        {life.transitions.map((t, i) => (
          <li key={`${t.at}-${t.to_state}-${i}`} className="tl-item" data-current={i === life.transitions.length - 1 ? "true" : "false"}>
            <span className="tl-node tl-node-known" aria-hidden="true" />
            <div className="min-w-0">
              <p className="tl-time num">{when(t.at)}</p>
              <p className="tl-title">
                {t.from_state ? `${LIFECYCLE_LABEL[t.from_state]} → ` : ""}
                {LIFECYCLE_LABEL[t.to_state]}
              </p>
              <p className="tl-sub">{t.rule_text}</p>
              {t.evidence_quote && <p className="tl-sub">Evidence: “{t.evidence_quote}”</p>}
              {t.evidence_report_ids.length === 0 && t.rule !== "FIRST_REPORT" && <p className="tl-sub">Caused by elapsed time, not by a new report.</p>}
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-2 max-w-[72ch] text-xs text-muted">{life.note}</p>
    </div>
  );
}

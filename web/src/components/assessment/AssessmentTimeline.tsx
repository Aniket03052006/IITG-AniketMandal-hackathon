import type { TimelineItem, TimelineView } from "../../api/types";
import { dateTime } from "../../lib/format";
import { AssessmentKind } from "./AssessmentKind";

const PHASE: { id: TimelineItem["phase"]; title: string; note: string }[] = [
  { id: "BEFORE_REPORT", title: "Before the report", note: "Known when the report appeared." },
  { id: "AT_REPORT", title: "At the report", note: "The report itself, and the moment EventShock read it." },
  { id: "AFTER_REPORT", title: "After the report", note: "Shown for audit. None of it can change the score." },
];

function Used({ i }: { i: TimelineItem }) {
  if (i.used_in_severity) return <span className="tag">used in the severity score</span>;
  if (i.used_by_reference_model) return <span className="tag">read by the reference model only</span>;
  return <span className="tag">not used</span>;
}

/** What EventShock knew, and when, in time order. Phase headings and a "used / not used" tag on every line, so nothing from after the report can look like an input. */
export function AssessmentTimeline({ tl }: { tl: TimelineView }) {
  return (
    <div>
      <p className="max-w-[72ch] text-sm text-muted">{tl.note}</p>
      <div className="mt-4 grid gap-8 lg:grid-cols-3">
        {PHASE.map((p) => {
          const items = tl.items.filter((i) => i.phase === p.id);
          return (
            <section key={p.id} aria-label={p.title}>
              <h4 className="text-sm font-semibold">{p.title}</h4>
              <p className="mb-2 text-xs text-muted">{p.note}</p>
              {items.length === 0 ? (
                <p className="text-sm text-muted">Nothing {p.id === "AFTER_REPORT" ? "later is known" : "recorded"}.</p>
              ) : (
                <ol>
                  {items.map((i, n) => (
                    <li key={`${i.kind}-${n}`} className="tl-item" data-phase={i.phase} data-used={i.used_in_severity ? "yes" : "no"}>
                      <p className="text-sm font-medium text-ink">{i.label}</p>
                      <p className="num text-xs text-muted">{i.at ? dateTime(i.at) : "time of the last session"}</p>
                      <p className="text-xs text-ink-2">{i.detail}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-1.5">
                        <AssessmentKind kind={i.number_kind} />
                        <Used i={i} />
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          );
        })}
      </div>
      <div className="mt-6 max-w-[72ch]">
        <p className="eyebrow">Deliberately excluded from the severity score</p>
        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-2">
          {tl.excluded.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

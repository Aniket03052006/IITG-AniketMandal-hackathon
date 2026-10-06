import { useEventExplanation, useMeta } from "../../api/hooks";
import type { ExplainSubject } from "../../api/types";
import { SUBJECT_TITLE } from "../../lib/explain";
import { Drawer, useOpenDrawer } from "../Drawer";
import { Question } from "../icons";
import { Skeleton, ErrorState } from "../ui";
import { ExplanationView } from "./ReasonList";

/** The URL key of a "Why?" drawer: `?open=why-priority`, so a link or a screenshot can land on it. */
export const whyKey = (s: ExplainSubject) => `why-${s.toLowerCase()}`;

/** Buttons that open the structured "Why?" drawers of an event. Hidden where explanations are not served. */
export function WhyButtons({ subjects, size = "sm" }: { subjects: ExplainSubject[]; size?: "sm" | "md" }) {
  const { data: meta } = useMeta();
  const [, setOpen] = useOpenDrawer();
  if (meta?.capabilities.explanations !== true) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Why?">
      {subjects.map((s) => (
        <button key={s} type="button" className={size === "sm" ? "btn btn-sm" : "btn"} aria-haspopup="dialog" onClick={() => setOpen(whyKey(s))}>
          <Question size={14} /> {SUBJECT_TITLE[s] ?? "Why?"}
        </button>
      ))}
    </div>
  );
}

/** The drawers themselves: one per subject, fetched only while open. */
export function WhyDrawers({ eventId, subjects, cycle = null, changeId = null }: { eventId: string | undefined; subjects: ExplainSubject[]; cycle?: number | null; changeId?: string | null }) {
  const [open, setOpen] = useOpenDrawer();
  const { data: meta } = useMeta();
  const on = meta?.capabilities.explanations === true;
  const active = subjects.find((s) => whyKey(s) === open) ?? null;
  const q = useEventExplanation(eventId, (active ?? "PRIORITY") as ExplainSubject, on && !!active, cycle, changeId);
  if (!on) return null;
  return (
    <Drawer open={!!active} onClose={() => setOpen(null)} title={active ? (SUBJECT_TITLE[active] ?? "Why?") : "Why?"} eyebrow="Explanation" wide>
      {q.isLoading && <div className="space-y-3"><Skeleton className="h-6 w-2/3" /><Skeleton className="h-32 w-full" /></div>}
      {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
      {q.data && <ExplanationView e={q.data} />}
    </Drawer>
  );
}

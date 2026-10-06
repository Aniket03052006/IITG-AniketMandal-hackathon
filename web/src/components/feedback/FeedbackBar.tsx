import { useState } from "react";
import { useMeta, usePostFeedback } from "../../api/hooks";
import type { FeedbackType, FeedbackValue } from "../../api/types";
import { ErrorState } from "../ui";

const GROUPS: { type: FeedbackType; label: string; options: { value: FeedbackValue; label: string }[] }[] = [
  { type: "RELEVANCE", label: "Is it relevant to you?", options: [{ value: "RELEVANT", label: "Relevant" }, { value: "PARTIALLY_RELEVANT", label: "Partly" }, { value: "IRRELEVANT", label: "Irrelevant" }] },
  { type: "SCOPE", label: "Is the scope right?", options: [{ value: "CORRECT", label: "Correct" }, { value: "INCORRECT", label: "Incorrect" }] },
  { type: "EVENT", label: "Is the event right?", options: [{ value: "CORRECT", label: "Correct" }, { value: "INCORRECT", label: "Incorrect" }] },
];

/** Tell EventShock what you think of this event. It is analyst feedback: recorded and counted, not ground truth, and it never changes a model or a score. */
export function FeedbackBar({ eventId, cycle = null }: { eventId: string; cycle?: number | null }) {
  const { data: meta } = useMeta();
  const post = usePostFeedback();
  const [picked, setPicked] = useState<Partial<Record<FeedbackType, FeedbackValue>>>({});
  const [comment, setComment] = useState("");
  const [saved, setSaved] = useState<number | null>(null);
  if (meta?.capabilities.feedback !== true) return null;
  const n = Object.values(picked).filter(Boolean).length;
  const send = async () => {
    let ok = 0;
    for (const g of GROUPS) {
      const v = picked[g.type];
      if (!v) continue;
      await post.mutateAsync({ event_id: eventId, type: g.type, value: v, comment: comment.trim() || null, cycle } as never);
      ok++;
    }
    setSaved(ok);
    setPicked({});
    setComment("");
  };
  return (
    <details className="disclosure">
      <summary>Give feedback on this event</summary>
      <form className="mt-3 space-y-3" aria-label="Analyst feedback" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        {GROUPS.map((g) => (
          <fieldset key={g.type} className="flex flex-wrap items-center gap-2">
            <legend className="eyebrow mb-1 w-full">{g.label}</legend>
            {g.options.map((o) => (
              <button key={o.value} type="button" className="chip" aria-pressed={picked[g.type] === o.value} onClick={() => setPicked({ ...picked, [g.type]: picked[g.type] === o.value ? undefined : o.value })}>{o.label}</button>
            ))}
          </fieldset>
        ))}
        <label className="block">
          <span className="eyebrow block">Comment (optional)</span>
          <textarea className="field mt-1 w-full max-w-[40rem]" rows={2} maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" className="btn btn-primary btn-sm" disabled={n === 0 || post.isPending}>{post.isPending ? "Saving…" : "Send feedback"}</button>
          {saved != null && <span role="status" className="text-sm text-ink-2">Recorded {saved} answer{saved === 1 ? "" : "s"}. Thank you.</span>}
        </div>
        {post.error && <ErrorState error={post.error as Error} />}
        <p className="max-w-[64ch] text-xs text-muted">Analyst feedback is recorded and counted. It is not ground truth and it does not change any model, score or threshold: EventShock does not learn from it.</p>
      </form>
    </details>
  );
}

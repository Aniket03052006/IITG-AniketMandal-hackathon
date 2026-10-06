import { useFeedbackStats } from "../../api/hooks";
import type { TypeStats } from "../../api/types";
import { pct } from "../../lib/format";
import { StateNotice } from "../StateNotice";
import { ErrorState, Skeleton } from "../ui";

function Tile({ label, s, agree }: { label: string; s: TypeStats; agree: string }) {
  return (
    <div className="tile" role="group" aria-label={label}>
      <p className="eyebrow">{label}</p>
      <p className="mt-1.5 font-display text-xl font-semibold">{s.agreement != null ? pct(s.agreement, 0) : "n/a"}</p>
      <p className="mt-1 text-sm text-ink-2">{agree}{s.type === "RELEVANCE" && s.at_least_partly_relevant != null ? `; ${pct(s.at_least_partly_relevant, 0)} at least partly relevant` : ""}. {s.total} answer{s.total === 1 ? "" : "s"}.</p>
    </div>
  );
}

/** What analysts have said, counted. Clearly analyst feedback: not ground truth, and nothing here changes a model. */
export function FeedbackStatsTab() {
  const q = useFeedbackStats();
  if (q.isLoading) return <Skeleton className="h-32 w-full" />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const s = q.data;
  if (!s) return null;
  return (
    <div className="space-y-4">
      <StateNotice tone="info" what="Analyst feedback, not ground truth." why={s.note} />
      <div className="tiles" role="list" aria-label="Feedback statistics">
        <div className="tile" role="group" aria-label="Feedback volume"><p className="eyebrow">Feedback volume</p><p className="mt-1.5 font-display text-xl font-semibold">{s.volume}</p><p className="mt-1 text-sm text-ink-2">{s.events} event{s.events === 1 ? "" : "s"}, {s.analysts} analyst{s.analysts === 1 ? "" : "s"}.</p></div>
        <Tile label="Relevance agreement" s={s.relevance} agree="share marked relevant" />
        <Tile label="Scope agreement" s={s.scope} agree="share marked correct" />
        <Tile label="Event agreement" s={s.event} agree="share marked correct" />
        <div className="tile" role="group" aria-label="Unresolved feedback"><p className="eyebrow">Unresolved feedback</p><p className="mt-1.5 font-display text-xl font-semibold">{s.needs_review}</p><p className="mt-1 text-sm text-ink-2">event/type pairs with a negative answer to review; {s.disagreements} where analysts disagree.</p></div>
      </div>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">{s.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
    </div>
  );
}

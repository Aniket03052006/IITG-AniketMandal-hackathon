import { useState } from "react";
import { useExplainReverse, useExplainScenario, useMeta } from "../../api/hooks";
import type { Explanation, ReverseStressRequest, ScenarioRequest } from "../../api/types";
import { Question } from "../icons";
import { ErrorState, Skeleton } from "../ui";
import { ExplanationView } from "./ReasonList";

function Shell({ label, pending, error, data, onAsk }: { label: string; pending: boolean; error: Error | null; data: Explanation | undefined; onAsk: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" className="btn btn-sm" aria-expanded={open} onClick={() => { if (!open && !data) onAsk(); setOpen(!open); }}>
        <Question size={14} /> {open ? "Hide the reasons" : label}
      </button>
      {open && (
        <div className="mt-3 rounded-sm border border-rule bg-paper-3 p-4" aria-live="polite">
          {pending && <Skeleton className="h-24 w-full" />}
          {error && <ErrorState error={error} />}
          {data && <ExplanationView e={data} />}
        </div>
      )}
    </div>
  );
}

/** "Why this result?" for a scenario of the lab: the assumptions, what each reached and the engine's decomposition, as structured reasons. */
export function WhyScenario({ req }: { req: ScenarioRequest }) {
  const { data: meta } = useMeta();
  const m = useExplainScenario();
  if (meta?.capabilities.explanations !== true) return null;
  return <Shell label="Why this result?" pending={m.isPending} error={m.error as Error | null} data={m.data} onAsk={() => m.mutate(req)} />;
}

/** "Why these shocks?" for a reverse-stress answer. */
export function WhyReverse({ req }: { req: Omit<ReverseStressRequest, "portfolio_id"> }) {
  const { data: meta } = useMeta();
  const m = useExplainReverse();
  if (meta?.capabilities.explanations !== true) return null;
  return <Shell label="Why these shocks?" pending={m.isPending} error={m.error as Error | null} data={m.data} onAsk={() => m.mutate(req)} />;
}

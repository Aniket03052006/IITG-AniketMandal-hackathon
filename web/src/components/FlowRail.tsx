import clsx from "clsx";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check } from "./icons";

/** The chain the whole product tells: unstructured text -> event understanding -> impact -> evidence -> scenario/stress. */
export type Stage = "event" | "understand" | "impact" | "evidence" | "stress";

export const STAGES: { id: Stage; label: string; says: string }[] = [
  { id: "event", label: "Event", says: "What was reported" },
  { id: "understand", label: "Understand", says: "NLP reads the text: event type and sentiment" },
  { id: "impact", label: "Impact", says: "How severe a market reaction is likely" },
  { id: "evidence", label: "Evidence", says: "What supports it, and what was known when" },
  { id: "stress", label: "Stress", says: "What a scenario does to the portfolio" },
];

/**
 * Sticky analytical trace of where you are in the chain. Not an onboarding stepper: nodes are the same stages the page is
 * built from, the current one is named in full, and each is a link (an anchor on the Event page, a route elsewhere).
 */
export function FlowRail({
  active,
  eventId,
  context,
  onNavigate,
  className,
}: {
  active: Stage;
  eventId?: string;
  context?: ReactNode;
  /** Event page: scroll to a chapter in place instead of following a link. */
  onNavigate?: (stage: Stage) => void;
  className?: string;
}) {
  const at = STAGES.findIndex((s) => s.id === active);
  const target = (s: Stage) => {
    if (s === "stress") return eventId ? `/stress?signal=${eventId}` : "/stress";
    return eventId ? `/events/${eventId}#${s}` : "/";
  };
  return (
    <nav aria-label="EventShock chain" className={clsx("flow", className)}>
      {context && <div className="flow-context">{context}</div>}
      <ol className="flow-track">
        {STAGES.map((s, i) => {
          const state = i < at ? "done" : i === at ? "active" : "todo";
          const inner = (
            <>
              <span className="flow-node" aria-hidden="true">
                {state === "done" ? <Check size={11} /> : <span className="flow-dot" />}
              </span>
              <span className={clsx("flow-label", state !== "active" && "flow-label-short")}>{s.label}</span>
            </>
          );
          return (
            <li key={s.id} className="flow-step" data-state={state} aria-current={state === "active" ? "step" : undefined}>
              {onNavigate && s.id !== "stress" ? (
                <button type="button" className="flow-link" onClick={() => onNavigate(s.id)} title={s.says}>
                  {inner}
                </button>
              ) : (
                <Link className="flow-link" to={target(s.id)} title={s.says}>
                  {inner}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

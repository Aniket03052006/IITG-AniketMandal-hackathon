import clsx from "clsx";
import type { ReactNode } from "react";
import { Alert, Info } from "./icons";

/**
 * Every unusual state answers three questions in order: WHAT happened, WHY, and WHAT THE USER CAN DO NEXT.
 * `details` is the optional "Why?" depth (an expander or a drawer trigger), never required reading.
 */
export function StateNotice({
  tone = "info",
  what,
  why,
  next,
  details,
  className,
}: {
  tone?: "info" | "warn" | "neg";
  what: string;
  why: ReactNode;
  next?: ReactNode;
  details?: ReactNode;
  className?: string;
}) {
  const Ico = tone === "info" ? Info : Alert;
  return (
    <div role={tone === "neg" ? "alert" : "status"} className={clsx("state-notice", `state-${tone}`, className)}>
      <Ico size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-ink">{what}</p>
        <p className="mt-1 text-sm text-ink-2">{why}</p>
        {details && <div className="mt-2 text-sm text-ink-2">{details}</div>}
        {next && <div className="mt-3 flex flex-wrap items-center gap-2">{next}</div>}
      </div>
    </div>
  );
}

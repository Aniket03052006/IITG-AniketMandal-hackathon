import { Link } from "react-router-dom";
import { ArrowRight } from "../icons";
import { StateNotice } from "../StateNotice";

/**
 * The one place the trigger is explained, used wherever a severity score appears. A score is a triage level, never a forecast, and the notice
 * always says what happens next: above the trigger a scenario is suggested; below it nothing runs by itself but a what-if is one click away.
 */
export function ThresholdNotice({
  score,
  threshold,
  signalId,
  compact = false,
  action = true,
}: {
  score: number | null;
  threshold: number;
  signalId?: string;
  compact?: boolean;
  action?: boolean;
}) {
  if (score === null) {
    return (
      <StateNotice
        tone="info"
        what="No severity score, so nothing can trigger"
        why="EventShock does not score text that is not a market event, and never substitutes a default number."
      />
    );
  }
  const crosses = score >= threshold;
  const to = signalId ? `/stress?signal=${signalId}${crosses ? "&run=1" : ""}` : undefined;
  return (
    <StateNotice
      tone={crosses ? "warn" : "info"}
      className={compact ? "!p-3" : undefined}
      what={crosses ? `Severity ${score}/10 is above the automatic trigger (${threshold})` : `Severity ${score}/10 is below the automatic trigger (${threshold})`}
      why={
        crosses
          ? "The default scenario is suggested and can run now. The score is a triage level for the book, not a forecast of a price move."
          : "No stress runs automatically. You can still run it as a what-if. The score is a triage level, not a forecast."
      }
      next={
        action && to ? (
          <Link className={crosses ? "btn btn-primary" : "btn"} to={to}>
            {crosses ? "Run the scenario" : "Run as a what-if"} <ArrowRight size={14} />
          </Link>
        ) : undefined
      }
    />
  );
}

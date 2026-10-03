import clsx from "clsx";
import { useEffect, useState } from "react";
import type { RiskSignal, SignalContext } from "../../api/types";
import { dateTime, sigma } from "../../lib/format";
import { impactKind } from "../../lib/impact";
import { assessmentIndex, buildMoments, hiddenCountAt, phaseAt, visibleAt, type Lane } from "../../lib/timeline";
import { StateNotice } from "../StateNotice";
import { Skeleton } from "../ui";

const LANE: Record<Lane, { label: string; says: string }> = {
  known: { label: "Available at the time", says: "Known to EventShock when it scored the report" },
  later: { label: "Learned later", says: "Published or filed after the report; never read by the model" },
  realised: { label: "Realised outcome", says: "What the market did afterwards; never an input" },
};

function LaneChip({ lane }: { lane: Lane }) {
  return (
    <span className={clsx("tl-chip", `tl-chip-${lane}`)} title={LANE[lane].says}>
      <span className={clsx("tl-node", `tl-node-${lane}`)} aria-hidden="true" />
      {LANE[lane].label}
    </span>
  );
}

/**
 * "What did EventShock know at this moment?" A slider moves a cursor through the story's life; the list shows everything the cursor has
 * reached and, past it, only empty placeholders: a later fact is not in the page at all in an earlier state. The three lanes differ in
 * node shape, pattern and name, so colour is never the only signal.
 */
export function KnowledgeTimeline({
  s,
  ctx,
  loading,
  error,
  label,
}: {
  s: RiskSignal;
  ctx: SignalContext | undefined;
  loading: boolean;
  error: Error | null;
  label: (c: string) => string;
}) {
  const synthetic = s.provenance?.timestamp_origin === "SYNTHETIC_REPLAY_CLOCK";
  const moments = buildMoments(s, ctx);
  const start = assessmentIndex(moments);
  const [cursor, setCursor] = useState(start);
  useEffect(() => setCursor(start), [start, moments.length]); // follow the data when the context arrives

  if (synthetic) {
    return (
      <StateNotice
        tone="info"
        what="No timeline for this post"
        why="The source gave no time, so the replay assigned one. Ordering events against an invented time would mislead, so none is drawn."
      />
    );
  }
  if (loading) return <Skeleton className="h-40 w-full" />;
  if (error) {
    return <StateNotice tone="warn" what="The filing and outcome context could not be loaded" why={error.message} next={<span className="text-sm text-muted">The report itself is still shown below.</span>} />;
  }

  const shown = visibleAt(moments, cursor);
  const hidden = hiddenCountAt(moments, cursor);
  const phase = phaseAt(moments, cursor);
  const now = moments[Math.min(cursor, moments.length - 1)]!;
  const impact = s.impact;
  const kind = impactKind(s);
  const single = moments.length <= 2;
  const lanesPresent = (["known", "later", "realised"] as const).filter((l) => moments.some((m) => m.lane === l));

  const estimate =
    impact != null
      ? `Impact ${impact.score}/10${impact.score_low != null && impact.score_high != null ? ` (comparable events realised ${impact.score_low} to ${impact.score_high})` : ""}, ${s.event.status === "CLASSIFIED" ? label(s.event.category).toLowerCase() : "no committed event type"}, ${s.sentiment.score > 0.15 ? "positive" : s.sentiment.score < -0.15 ? "negative" : "neutral"} tone`
      : "no impact score";
  const realised = ctx?.outcome;

  return (
    <div className="tl">
      <ul className="tl-legend" aria-label="Legend">
        {lanesPresent.map((l) => (
          <li key={l}>
            <LaneChip lane={l} />
          </li>
        ))}
      </ul>

      {single ? (
        <p className="mb-4 text-sm text-muted">Only this report is on record for the story, so there is nothing to move through.</p>
      ) : (
        <div className="tl-controls">
          <label htmlFor="tl-range" className="eyebrow">
            Move through time
          </label>
          <input
            id="tl-range"
            type="range"
            min={0}
            max={moments.length - 1}
            step={1}
            value={cursor}
            onChange={(e) => setCursor(Number(e.target.value))}
            aria-valuetext={`${now.at ? dateTime(now.at) : "afterwards"}: ${now.title}`}
          />
          <div className="tl-now" aria-live="polite">
            <span className="num text-xs text-muted">{now.at ? dateTime(now.at) : "afterwards"}</span>
            <span className="font-medium">{now.title}</span>
            {cursor !== start && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setCursor(start)}>
                Back to the moment it was scored
              </button>
            )}
          </div>
        </div>
      )}

      <div className="tl-state" role="status">
        {phase === "before" && (
          <p>
            <strong>Before the report.</strong> EventShock has no reading of this story yet. It holds only the filings above, and the scores do not exist.
          </p>
        )}
        {phase === "assessed" && (
          <p>
            <strong>The moment it was scored.</strong> EventShock holds the filings above and the report itself, and its whole estimate comes from exactly that: <span className="text-ink">{estimate}</span>
            {impact != null && kind === "placeholder" ? " (placeholder rule)" : ""}.
          </p>
        )}
        {phase === "later" && (
          <p>
            <strong>More has arrived since.</strong> The estimate is unchanged ({estimate}), because it was fixed from what was known at the report. The hatched items are learned later and were never read by the model.
          </p>
        )}
        {phase === "realised" && realised && (
          <p>
            <strong>What actually happened.</strong> The market moved {sigma(realised.abs_z)}
            {impact?.predicted_severity != null ? `, against an estimate of ${sigma(impact.predicted_severity)}` : ""}. This is an observation after the fact, not something EventShock knew
            {impact?.score_low != null && impact.score_high != null
              ? `; the realised score (${realised.score}) ${realised.score >= impact.score_low && realised.score <= impact.score_high ? "lies inside" : "lies outside"} the range the model stated (${impact.score_low} to ${impact.score_high}).`
              : "."}
          </p>
        )}
      </div>

      <ol className="tl-track" style={{ ["--n" as string]: moments.length }} aria-label="Events in time order, up to the cursor">
        {shown.map((m) => (
          <li key={m.id} className="tl-item" data-lane={m.lane} data-current={m === now ? "true" : undefined}>
            <span className={clsx("tl-node", `tl-node-${m.lane}`)} aria-hidden="true" />
            <div className="min-w-0">
              <p className="tl-time num">{m.at ? dateTime(m.at) : "afterwards"}</p>
              <p className="tl-title">
                {m.title} <span className="sr-only">({LANE[m.lane].label})</span>
              </p>
              <p className="tl-sub">{m.sub}</p>
            </div>
          </li>
        ))}
        {Array.from({ length: hidden }, (_, i) => (
          <li key={`future-${i}`} className="tl-item tl-future" aria-hidden="true">
            <span className="tl-node tl-node-future" />
          </li>
        ))}
      </ol>

      {!realised && ctx && ctx.outcome_note && <p className="mt-3 text-xs text-muted">Realised outcome: {ctx.outcome_note}.</p>}
      {ctx?.filings_note && <p className="mt-1 text-xs text-muted">Filings: {ctx.filings_note}.</p>}
      {s.provenance?.timestamp_origin === "GDELT_FIRST_SEEN" && (
        <p className="mt-1 text-xs text-warn">This report's time is when GDELT first saw the page, which lags publication; the order of nearby events is approximate.</p>
      )}
    </div>
  );
}

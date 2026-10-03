import { Link } from "react-router-dom";
import type { RiskSignal } from "../../api/types";
import { dateTime } from "../../lib/format";
import { ruleNote, timestampNote } from "../../lib/provenance";
import { EventStatusTag } from "../EventStatusTag";
import { Alert } from "../icons";
import { StateNotice } from "../StateNotice";
import { SourceBadge, StatusTag } from "../ui";
import { ImpactVerdict } from "./ImpactVerdict";

/** First viewport: what happened, who, when, what was detected, how severe. The headline dominates; everything else is secondary. */
export function EventHero({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const unresolved = s.entity.entity_id === "UNKNOWN_ENTITY";
  const origin = s.provenance?.timestamp_origin;
  const ea = s.provenance?.entity_audit;
  return (
    <header id="event" className="hero" aria-labelledby="event-headline">
      <div className="hero-main">
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          <EventStatusTag status={s.event.status} category={s.event.category} label={label} />
          <SourceBadge type={s.document.source_type} name={s.document.source} />
          <span className="num text-xs text-muted">{dateTime(s.document.published_at)}</span>
          {origin && origin !== "SOURCE" && (
            <span className="text-xs text-warn" title={timestampNote(origin)}>
              {origin === "SYNTHETIC_REPLAY_CLOCK" ? "time assigned by replay" : origin === "GDELT_FIRST_SEEN" ? "time is when GDELT first saw it" : timestampNote(origin).toLowerCase()}
            </span>
          )}
          {s.status === "PARTIAL" && s.event.status === "CLASSIFIED" && (
            <StatusTag tone="warn" icon={<Alert size={12} />}>
              Partial signal
            </StatusTag>
          )}
        </div>
        <h1 id="event-headline" className="hero-title">
          {s.document.headline}
        </h1>
        {unresolved ? (
          <div className="mt-5 max-w-[60ch]">
            <StateNotice
              tone="warn"
              what="Company not identified"
              why="EventShock could not confidently link this story to a company. Company-specific portfolio stress is therefore unavailable."
              details={
                <details className="disclosure">
                  <summary>Why?</summary>
                  <p className="mt-2 text-sm">
                    {ea ? `${ruleNote(ea.rule)}.` : "No company name or ticker matched the entity list."}
                    {ea && ea.rejected.length > 0 ? ` Refused: ${ea.rejected.map((r) => `${r.matched_text} (${r.reason})`).join("; ")}.` : ""}
                    {ea && ea.candidates.length > 0 ? ` Considered: ${ea.candidates.map((c) => c.entity_name).join(", ")}.` : ""}
                  </p>
                </details>
              }
              next={
                <Link className="btn" to={`/stress?signal=${s.id}`}>
                  Use market-wide scenario
                </Link>
              }
            />
          </div>
        ) : (
          <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-md text-ink-2">
            <span className="font-medium text-ink">{s.entity.entity_name}</span>
            <span className="num text-muted">{s.entity.ticker}</span>
            <span className="text-muted">{s.entity.sector}</span>
            <span className="text-sm text-muted">linked with {(s.entity.link_confidence * 100).toFixed(0)}% confidence</span>
          </p>
        )}
      </div>
      <aside className="hero-verdict" aria-label="Impact verdict">
        <ImpactVerdict s={s} />
      </aside>
    </header>
  );
}

import { Link } from "react-router-dom";
import type { EventCategory, RiskAssessment, RiskSignal } from "../../api/types";
import { dateTime } from "../../lib/format";
import { REGION_LABEL, subjectLine, subjectOf } from "../../lib/scope";
import { ruleNote, timestampNote } from "../../lib/provenance";
import { EventStatusTag } from "../EventStatusTag";
import { Alert } from "../icons";
import { ScopeTag } from "../scope/Tags";
import { StateNotice } from "../StateNotice";
import { SourceBadge, StatusTag } from "../ui";
import { SeverityVerdict } from "../assessment/SeverityVerdict";
import { ImpactVerdict } from "./ImpactVerdict";
import { WatchButton } from "../watchlist/WatchButton";

/** First viewport: what happened, who, when, what was detected, how severe. The headline dominates; everything else is secondary. */
export function EventHero({ s, label, a, threshold }: { s: RiskSignal; label: (c: string) => string; a?: RiskAssessment; threshold: number }) {
  const sc = s.scope;
  const origin = s.provenance?.timestamp_origin;
  const ea = s.provenance?.entity_audit;
  return (
    <header id="event" className="hero" aria-labelledby="event-headline">
      <div className="hero-main">
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
          {a ? (
            <EventStatusTag status={a.reading.event_type === "NO_EVENT" ? "NO_EVENT" : "CLASSIFIED"} category={(a.reading.event_type === "NO_EVENT" ? s.event.category : a.reading.event_type) as EventCategory} label={label} />
          ) : (
            <EventStatusTag status={s.event.status} category={s.event.category} label={label} />
          )}
          <SourceBadge type={s.document.source_type} name={s.document.source} />
          <span className="num text-xs text-muted">{dateTime(s.document.published_at)}</span>
          {origin && origin !== "SOURCE" && (
            <span className="text-xs text-warn" title={timestampNote(origin)}>
              {origin === "SYNTHETIC_REPLAY_CLOCK" ? "time assigned by replay" : origin === "GDELT_FIRST_SEEN" ? "time is when GDELT first saw it" : origin === "ANALYSIS_TIME" ? "time is when it was pasted" : origin === "USER_ASSERTED" ? "time given by the person who pasted it" : timestampNote(origin).toLowerCase()}
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
        {sc.level === "COMPANY" ? (
          <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-md text-ink-2">
            <span className="font-medium text-ink">{s.entity.entity_name}</span>
            <span className="num text-muted">{s.entity.ticker}</span>
            <span className="text-muted">{s.entity.sector}</span>
            <span className="text-sm text-muted">linked with {(s.entity.link_confidence * 100).toFixed(0)}% confidence</span>
          </p>
        ) : sc.level === "UNRESOLVED" ? (
          <div className="mt-5 max-w-[60ch]">
            <StateNotice
              tone="warn"
              what="No subject identified"
              why={`${sc.note} The event is kept, and its type and tone are still read; nothing is guessed about who it concerns.`}
              details={
                <details className="disclosure">
                  <summary>Why no company?</summary>
                  <p className="mt-2 text-sm">
                    {ea ? `${ruleNote(ea.rule)}.` : "No company name or ticker matched the entity list."}
                    {ea && ea.rejected.length > 0 ? ` Refused: ${ea.rejected.map((r) => `${r.matched_text} (${r.reason})`).join("; ")}.` : ""}
                    {ea && ea.candidates.length > 0 ? ` Considered: ${ea.candidates.map((c) => c.entity_name).join(", ")}.` : ""}
                  </p>
                </details>
              }
              next={
                s.impact || a?.severity ? (
                  <Link className="btn" to={`/stress?signal=${s.id}`}>
                    See what market-wide shocks would do
                  </Link>
                ) : undefined
              }
            />
          </div>
        ) : (
          <div className="mt-4 max-w-[64ch]">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-md text-ink-2">
              <ScopeTag level={sc.level} sector={sc.sector} strength={sc.strength} />
              <span className="font-medium text-ink">{subjectLine(subjectOf(s))}</span>
              {sc.regions.length > 0 && <span className="text-sm text-muted">{sc.regions.map((r) => REGION_LABEL[r] ?? r).join(", ")}</span>}
            </p>
            <p className="mt-2 text-sm text-muted">{sc.note}</p>
          </div>
        )}
        <div className="mt-4"><WatchButton s={s} eventType={a ? a.reading.event_type : s.event.status === "CLASSIFIED" ? s.event.category : null} /></div>
      </div>
      <aside className="hero-verdict" aria-label={a ? "Severity verdict" : "Impact verdict"}>
        {a ? <SeverityVerdict a={a} threshold={threshold} /> : <ImpactVerdict s={s} />}
      </aside>
    </header>
  );
}

import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useAssessment, useMeta, useScenarios, useSignal, useSignalContext, useSignalEvidence, useSignalTimeline } from "../api/hooks";
import { SeverityChapter } from "../components/assessment/SeverityChapter";
import { ArrowLeft } from "../components/icons";
import { ChainGraphic } from "../components/event/ChainGraphic";
import { EventDrawers } from "../components/event/Drawers";
import { EventHero } from "../components/event/EventHero";
import { EvidenceChapter } from "../components/event/EvidenceChapter";
import { ImpactChapter } from "../components/event/ImpactChapter";
import { IntelligencePanel } from "../components/intelligence/IntelligencePanel";
import { StressBridge } from "../components/event/StressBridge";
import { UnderstandChapter } from "../components/event/UnderstandChapter";
import { FlowRail, type Stage } from "../components/FlowRail";
import { ErrorState, Skeleton } from "../components/ui";
import { useChapterSpy } from "../lib/motion";
import { rememberEvent } from "../lib/featured";
import { subjectLine, subjectOf } from "../lib/scope";
import { categoryLabeler } from "../lib/taxonomy";

const CHAPTERS = ["event", "understand", "impact", "evidence", "stress"] as const satisfies readonly Stage[];

function EventSkeleton() {
  return (
    <div role="status" aria-label="Loading event" className="space-y-6">
      <Skeleton className="h-6 w-1/3" />
      <Skeleton className="h-24 w-3/4" />
      <Skeleton className="h-64 w-full" />
    </div>
  );
}

/** The flagship screen: one event told as a story, from the text to the portfolio, with every explanation one click away. */
export function EventPage() {
  const { id } = useParams();
  const { hash } = useLocation();
  const { data: s, error, isLoading, refetch } = useSignal(id);
  const { data: meta } = useMeta();
  const scenarios = useScenarios();
  const ctx = useSignalContext(s?.id);
  // the risk assessment exists only where the engine does (replay profile); without it the page keeps the trained-model view
  const assessed = meta?.capabilities.assessment === true;
  const asm = useAssessment(s?.id, assessed);
  const evid = useSignalEvidence(s?.id, assessed);
  const tl = useSignalTimeline(s?.id, assessed);
  const a = assessed ? asm.data : undefined;
  const label = categoryLabeler(meta);
  const [active, go] = useChapterSpy(CHAPTERS, !!s);

  useEffect(() => {
    if (s) rememberEvent(s.id);
  }, [s]);

  useEffect(() => {
    if (!s || !hash) return;
    document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [s, hash]);

  const threshold = meta?.trigger_threshold ?? 7;
  // with an assessment the scenario follows the ASSESSED event class; without one, only a classified trained reading maps to a scenario
  const category = a ? (a.reading.event_type === "NO_EVENT" ? undefined : a.reading.event_type) : s?.event.status === "CLASSIFIED" ? s.event.category : undefined;
  const scenarioId = category ? scenarios.data?.default_by_category[category as keyof typeof scenarios.data.default_by_category] : undefined;
  const scenario = category ? scenarios.data?.scenarios.find((x) => x.id === scenarioId) : undefined;
  const score = a ? (a.severity?.score ?? null) : (s?.impact?.score ?? null);
  const triggers = score !== null && score >= threshold;

  return (
    <>
      <Link to="/" className="btn btn-ghost mb-3 -ml-3">
        <ArrowLeft size={14} /> Risk Feed
      </Link>
      {isLoading && <EventSkeleton />}
      {error && (
        <ErrorState
          error={error.message.includes("not found") ? new Error(`No event with id “${id}”. It may belong to a different data profile.`) : error}
          retry={() => refetch()}
        />
      )}
      {s && (
        <>
          <FlowRail
            active={active}
            eventId={s.id}
            onNavigate={(st) => go(st as (typeof CHAPTERS)[number])}
            context={
              <>
                <span className="font-medium text-ink">{subjectLine(subjectOf(s))}</span>
                {a ? (a.reading.event_type === "NO_EVENT" ? "" : ` · ${label(a.reading.event_type)}`) : s.event.status === "CLASSIFIED" ? ` · ${label(s.event.category)}` : ""}
                {score !== null ? ` · ${a ? "severity" : "impact"} ${score}/10` : ""}
              </>
            }
          />
          <EventHero s={s} label={label} a={a} threshold={threshold} />
          <ChainGraphic
            s={s}
            label={label}
            scenarioName={scenario?.name}
            triggers={triggers}
            threshold={threshold}
            onGo={(st) => go(st)}
            a={a}
          />
          <IntelligencePanel signalId={s.id} enabled={meta?.capabilities.intelligence === true} />
          <UnderstandChapter s={s} label={label} a={a} />
          {a ? <SeverityChapter a={a} /> : <ImpactChapter s={s} label={label} />}
          <EvidenceChapter
            s={s}
            ctx={ctx.data}
            ctxLoading={ctx.isLoading}
            ctxError={ctx.error}
            asOf={meta?.as_of ?? s.created_at}
            label={label}
            a={a}
            evidence={evid.data}
            timeline={tl.data}
            assessLoading={assessed && (asm.isLoading || evid.isLoading || tl.isLoading)}
          />
          <StressBridge s={s} scenario={scenario} threshold={threshold} a={a} />
          <EventDrawers s={s} ctx={ctx.data} ctxLoading={ctx.isLoading} label={label} assessment={a} timeline={tl.data} />
        </>
      )}
    </>
  );
}

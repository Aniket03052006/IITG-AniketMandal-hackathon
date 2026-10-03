import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMeta, useScenarios, useSignal, useSignalContext } from "../api/hooks";
import { ArrowLeft } from "../components/icons";
import { ChainGraphic } from "../components/event/ChainGraphic";
import { EventDrawers } from "../components/event/Drawers";
import { EventHero } from "../components/event/EventHero";
import { EvidenceChapter } from "../components/event/EvidenceChapter";
import { ImpactChapter } from "../components/event/ImpactChapter";
import { StressBridge } from "../components/event/StressBridge";
import { UnderstandChapter } from "../components/event/UnderstandChapter";
import { FlowRail, type Stage } from "../components/FlowRail";
import { ErrorState, Skeleton } from "../components/ui";
import { useChapterSpy } from "../lib/motion";
import { rememberEvent } from "../lib/featured";
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
  const scenarioId = s ? scenarios.data?.default_by_category[s.event.category] : undefined;
  // a text that is not a classified market event maps to no scenario: its category is only a best guess
  const scenario = s?.event.status === "CLASSIFIED" ? scenarios.data?.scenarios.find((x) => x.id === scenarioId) : undefined;
  const triggers = !!s?.impact && s.impact.score >= threshold;

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
                <span className="font-medium text-ink">{s.entity.entity_name ?? "Company not identified"}</span>
                {s.event.status === "CLASSIFIED" ? ` · ${label(s.event.category)}` : ""}
                {s.impact ? ` · impact ${s.impact.score}/10` : ""}
              </>
            }
          />
          <EventHero s={s} label={label} />
          <ChainGraphic
            s={s}
            label={label}
            scenarioName={scenario?.name}
            triggers={triggers}
            threshold={threshold}
            onGo={(st) => go(st)}
          />
          <UnderstandChapter s={s} label={label} />
          <ImpactChapter s={s} label={label} />
          <EvidenceChapter
            s={s}
            ctx={ctx.data}
            ctxLoading={ctx.isLoading}
            ctxError={ctx.error}
            asOf={meta?.as_of ?? s.created_at}
            label={label}
          />
          <StressBridge s={s} scenario={scenario} threshold={threshold} />
          <EventDrawers s={s} ctx={ctx.data} ctxLoading={ctx.isLoading} label={label} />
        </>
      )}
    </>
  );
}

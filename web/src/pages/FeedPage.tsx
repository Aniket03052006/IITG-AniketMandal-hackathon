import clsx from "clsx";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMeta, useSignals } from "../api/hooks";
import type { Meta, SignalSummary } from "../api/types";
import { EVENT_CATEGORIES } from "../api/types";
import { Alert, ArrowRight, CATEGORY_ICON, Chevron, Search } from "../components/icons";
import { EmptyState, ErrorState, ImpactMeter, SentimentBar, Skeleton, SourceBadge, StatusTag } from "../components/ui";
import { EventStatusTag } from "../components/EventStatusTag";
import { StageStrip } from "../components/StageStrip";
import { ago } from "../lib/format";
import { FEATURED, pickAlso, pickFeatured } from "../lib/featured";
import { impactIsModel, servedKinds, summaryKind } from "../lib/impact";
import { eventIsModel, sentimentIsModel } from "../lib/provenance";
import { categoryLabeler } from "../lib/taxonomy";

type Sort = "newest" | "impact";

function FeedRow({ s, asOf, label }: { s: SignalSummary; asOf: string; label: (c: string) => string }) {
  const unknown = s.entity_id === "UNKNOWN_ENTITY";
  return (
    <li>
      <Link
        to={`/events/${s.id}`}
        className="group grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-2.5 border-b border-rule px-4 py-3.5 transition-colors duration-[var(--duration-fast)] hover:bg-paper-3 xl:grid-cols-[7.5rem_minmax(0,1fr)_9.5rem_3.75rem_4.25rem] xl:items-center"
      >
        <div className="pt-0.5 xl:pt-0">
          <ImpactMeter
            score={s.impact_score}
            kind={s.impact_score === null || s.data_origin === "DEMO_FIXTURE" ? undefined : summaryKind(s)}
            showKind={s.impact_score !== null && s.data_origin !== "DEMO_FIXTURE"}
          />
        </div>
        <div className="min-w-0">
          <p className="font-medium leading-snug text-ink group-hover:text-accent-strong">{s.headline}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            {unknown ? (
              <span className="text-warn">Entity unresolved</span>
            ) : (
              <>
                <span className="text-ink-2">{s.entity_name}</span>
                <span className="num">{s.ticker}</span>
                <span aria-hidden="true">·</span>
                <span>{s.sector}</span>
              </>
            )}
            <span aria-hidden="true">·</span>
            <SourceBadge type={s.source_type} name={s.source} />
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <EventStatusTag status={s.event_status} category={s.category} label={label} />
            {s.status === "PARTIAL" && s.event_status === "CLASSIFIED" && (
              <StatusTag tone="warn" icon={<Alert size={12} />}>Partial</StatusTag>
            )}
          </div>
        </div>
        <div className="col-span-2 flex flex-wrap items-center gap-x-4 gap-y-2 xl:contents">
          <SentimentBar score={s.sentiment_score} />
          <span className="num text-sm text-ink-2 xl:text-right" title="Sources reporting this narrative">
            {s.source_count}
            <span className="ml-1 text-xs text-muted xl:hidden">sources</span>
          </span>
          <span className="num text-xs text-muted xl:text-right">{ago(s.published_at, asOf)}</span>
        </div>
      </Link>
    </li>
  );
}

function FeedSkeleton() {
  return (
    <ul aria-hidden="true">
      {Array.from({ length: 6 }, (_, i) => (
        <li key={i} className="flex gap-4 border-b border-rule px-4 py-4">
          <Skeleton className="h-6 w-28" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function feedNote(meta: Meta | undefined): string {
  if (meta?.profile !== "replay") return "All demo fixtures (fixture-v0), not model output.";
  if (sentimentIsModel(meta) && eventIsModel(meta)) {
    return impactIsModel(meta)
      ? `Real documents. Sentiment and event type are trained models that can abstain; impact is a ${servedKinds(meta).join(" / ")} model where it can score a signal and a labelled placeholder rule elsewhere.`
      : "Real documents. Sentiment and event type are trained models that can abstain; impact is a placeholder rule.";
  }
  return sentimentIsModel(meta)
    ? "Real documents. Sentiment is a trained model; event type and impact are placeholder rules."
    : "Real documents, placeholder sentiment/event/impact (not model output).";
}

const PAGE = 30;

/** The whole chain in four real numbers, so the first screen explains what EventShock does before any filter is touched. */
function StoryStrip({ items, threshold, loading }: { items: SignalSummary[]; threshold: number; loading: boolean }) {
  const events = items.filter((s) => s.event_status === "CLASSIFIED");
  const notEvents = items.filter((s) => s.event_status === "NO_EVENT").length;
  const uncertain = items.filter((s) => s.event_status === "UNCERTAIN").length;
  const scored = items.filter((s) => s.impact_origin === "MODEL");
  const high = items.filter((s) => (s.impact_score ?? 0) >= threshold);
  const highModel = high.filter((s) => s.impact_origin === "MODEL").length;
  const n = (v: number) => (loading ? "–" : v.toLocaleString("en-US"));
  const steps = [
    { k: "Read", v: n(items.length), t: "reports and posts", d: "Real news and social text, validated, de-duplicated and linked to companies." },
    { k: "Understand", v: n(events.length), t: "market events found", d: `NLP sets an event type and sentiment. ${loading ? "" : `${notEvents.toLocaleString("en-US")} were judged not to be events and ${uncertain} left uncertain.`}` },
    { k: "Estimate", v: n(scored.length), t: "scored by the impact model", d: "An experimental model rates how severe the reaction is likely to be. The rest keep a labelled rule or no score." },
    { k: "Stress", v: n(high.length), t: `reach impact ≥ ${threshold}`, d: `These trigger a scenario on the portfolio${loading ? "" : ` (${highModel} on model output, ${high.length - highModel} on the placeholder rule)`}.` },
  ];
  return (
    <ol className="story" aria-label="What EventShock did with the data">
      {steps.map((st, i) => (
        <li key={st.k} className="story-step" style={{ ["--i" as string]: i }}>
          <p className="eyebrow">{st.k}</p>
          <p className="story-n num">{st.v}</p>
          <p className="font-medium text-ink">{st.t}</p>
          <p className="mt-1 text-sm text-muted">{st.d}</p>
        </li>
      ))}
    </ol>
  );
}

function FeaturedPanel({ items, label }: { items: SignalSummary[]; label: (c: string) => string }) {
  const hero = pickFeatured(items);
  const also = pickAlso(items);
  if (!hero) return null;
  return (
    <section className="featured" aria-labelledby="featured-h">
      <div className="min-w-0">
        <p className="eyebrow" id="featured-h">
          Start the guided demo
        </p>
        <p className="mt-2 font-display text-xl font-semibold leading-snug">{hero.headline}</p>
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
          <span className="text-ink-2">{hero.entity_name}</span>
          <span className="num">{hero.ticker}</span>
          <EventStatusTag status={hero.event_status} category={hero.category} label={label} />
        </p>
        <p className="mt-3 max-w-[58ch] text-sm text-muted">{hero.id === FEATURED.hero.id ? FEATURED.hero.why : "The highest-impact model-scored event in this data."}</p>
      </div>
      <div className="flex flex-col items-start gap-4 sm:items-end">
        <ImpactMeter score={hero.impact_score} kind={hero.impact_score === null ? undefined : summaryKind(hero)} showKind range={hero.impact_score_low != null && hero.impact_score_high != null ? [hero.impact_score_low, hero.impact_score_high] : null} />
        <Link to={`/events/${hero.id}`} className="btn btn-primary">
          Open the event story <ArrowRight size={14} />
        </Link>
      </div>
      {also.length > 0 && (
        <p className="featured-also">
          Also try:{" "}
          {also.map((a) => (
            <Link key={a.id} to={`/events/${a.id}`} className="text-accent underline underline-offset-2">
              {a.headline.length > 70 ? `${a.headline.slice(0, 68)}…` : a.headline}
            </Link>
          ))}{" "}
          <span className="text-muted">({FEATURED.also[0].why})</span>
        </p>
      )}
    </section>
  );
}

export function FeedPage() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const source = params.get("source") ?? "";
  const minImpact = Number(params.get("min") ?? 0) || undefined;
  const q = params.get("q") ?? "";
  const sort = (params.get("sort") as Sort) || "newest";
  const scoredOnly = params.get("scored") === "1";
  const [shown, setShown] = useState(PAGE);

  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const hasEventModel = eventIsModel(meta);
  const showNon = params.get("non") === "1" || !hasEventModel; // non-events are hidden by default once the model can say so
  const filters = { category: category || undefined, source_type: source || undefined, min_impact: minImpact, q: q || undefined };
  const { data, error, isLoading, refetch, isFetching } = useSignals(filters);
  const all = useSignals({}); // unfiltered, for the story strip

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setShown(PAGE);
  };

  const items = useMemo(() => {
    const rows = (data?.items ?? []).filter((s) => (showNon || s.event_status !== "NO_EVENT") && (!scoredOnly || s.impact_origin === "MODEL"));
    if (sort === "impact") rows.sort((a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1) || b.published_at.localeCompare(a.published_at));
    return rows;
  }, [data, sort, showNon, scoredOnly]);

  const threshold = meta?.trigger_threshold ?? 7;
  const everything = all.data?.items ?? [];
  const filtered = !!(category || source || minImpact || q || scoredOnly);
  const nonEvents = everything.filter((s) => s.event_status === "NO_EVENT").length;
  const moreFilters = !!(category || source || sort !== "newest");

  return (
    <>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Risk Feed</h1>
        <p className="mt-1 max-w-[64ch] text-md text-ink-2">
          EventShock reads financial text, works out what happened and how severe it is likely to be, and shows what that does to a portfolio. Start with the featured event, or browse.
        </p>
      </header>

      <StoryStrip items={everything} threshold={threshold} loading={all.isLoading} />
      {!all.isLoading && <FeaturedPanel items={everything} label={label} />}

      <details className="disclosure mt-5">
        <summary>What is real here, and what is a stand-in?</summary>
        <div className="mt-3 space-y-3">
          {meta?.replay && <StageStrip meta={meta} />}
          <p className="max-w-[72ch] text-sm text-muted">{feedNote(meta)}</p>
        </div>
      </details>

      <h2 className="mb-3 mt-10 text-lg font-semibold">All signals</h2>
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
            <span className="sr-only">Search signals</span>
            <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <input className="field pl-9" type="search" placeholder="Search headline, company, ticker" value={q} onChange={(e) => set("q", e.target.value || null)} />
          </label>
          <button type="button" className="chip" aria-pressed={minImpact === threshold} onClick={() => set("min", minImpact === threshold ? null : String(threshold))}>
            Impact ≥ {threshold}
          </button>
          {impactIsModel(meta) && (
            <button type="button" className="chip" aria-pressed={scoredOnly} onClick={() => set("scored", scoredOnly ? null : "1")}>
              Model-scored
            </button>
          )}
          {hasEventModel && (
            <button type="button" className="chip" aria-pressed={showNon} onClick={() => set("non", showNon ? null : "1")}>
              Show non-events{all.isLoading ? "" : ` (${nonEvents})`}
            </button>
          )}
          {filtered && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setParams({}, { replace: true })}>
              Clear filters
            </button>
          )}
        </div>
        <details className="disclosure" open={moreFilters || undefined}>
          <summary>More filters and sorting</summary>
          <div className="mt-3 flex flex-col gap-3">
            <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0" role="group" aria-label="Filter by event type">
              {EVENT_CATEGORIES.map((c) => {
                const Ico = CATEGORY_ICON[c];
                return (
                  <button key={c} type="button" className="chip" aria-pressed={category === c} onClick={() => set("category", category === c ? null : c)}>
                    <Ico size={13} /> {label(c)}
                  </button>
                );
              })}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1.5" role="group" aria-label="Filter by source">
                {[["", "All sources"], ["NEWS", "News"], ["SOCIAL", "Social"]].map(([v, l]) => (
                  <button key={v} type="button" className="chip" aria-pressed={source === v} onClick={() => set("source", v || null)}>
                    {l}
                  </button>
                ))}
              </div>
              <label className="flex items-center gap-2 text-sm text-muted">
                Sort
                <select className="field !w-auto" value={sort} onChange={(e) => set("sort", e.target.value === "newest" ? null : e.target.value)}>
                  <option value="newest">Newest</option>
                  <option value="impact">Highest impact</option>
                </select>
              </label>
            </div>
          </div>
        </details>
      </div>

      <section className="card overflow-hidden" aria-busy={isFetching} aria-label="Risk signals">
        <div className="hidden grid-cols-[7.5rem_minmax(0,1fr)_9.5rem_3.75rem_4.25rem] gap-x-4 border-b border-rule px-4 py-2 xl:grid" aria-hidden="true">
          {["Impact", "Event", "Sentiment", "Sources", "Seen"].map((h, i) => (
            <span key={h} className={clsx("eyebrow", i >= 3 && "text-right")}>{h}</span>
          ))}
        </div>
        {error ? (
          <div className="p-4"><ErrorState error={error} retry={() => refetch()} /></div>
        ) : isLoading ? (
          <FeedSkeleton />
        ) : items.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title="No signals match these filters"
              action={filtered ? <button className="btn" onClick={() => setParams({}, { replace: true })}>Clear filters</button> : undefined}
            >
              Loosen the impact threshold or event type to see more of the feed.
            </EmptyState>
          </div>
        ) : (
          <ul>
            {items.slice(0, shown).map((s) => (
              <FeedRow key={s.id} s={s} asOf={meta?.as_of ?? s.published_at} label={label} />
            ))}
          </ul>
        )}
        {items.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs text-muted">
            <p className="flex items-center gap-1.5">
              <Chevron size={12} /> {Math.min(shown, items.length)} of {items.length} signals shown
              {hasEventModel && !showNon && nonEvents > 0 ? ` (${nonEvents} judged not to be market events are hidden)` : ""}.
            </p>
            {shown < items.length && (
              <button type="button" className="btn btn-sm" onClick={() => setShown((n) => n + PAGE * 2)}>
                Show {Math.min(PAGE * 2, items.length - shown)} more
              </button>
            )}
          </div>
        )}
      </section>
    </>
  );
}

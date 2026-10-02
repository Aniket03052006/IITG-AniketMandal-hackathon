import clsx from "clsx";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMeta, useSignals } from "../api/hooks";
import type { SignalSummary } from "../api/types";
import { EVENT_CATEGORIES } from "../api/types";
import { Alert, CATEGORY_ICON, Chevron, Search } from "../components/icons";
import { CategoryTag, EmptyState, ErrorState, ImpactMeter, PageHeader, SentimentBar, Skeleton, SourceBadge, Stat, StatusTag } from "../components/ui";
import { ago, dateTime } from "../lib/format";
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
          <ImpactMeter score={s.impact_score} />
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
            <CategoryTag category={s.category} label={label(s.category)} />
            {s.status === "PARTIAL" && <StatusTag tone="warn" icon={<Alert size={12} />}>Partial</StatusTag>}
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

export function FeedPage() {
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const source = params.get("source") ?? "";
  const minImpact = Number(params.get("min") ?? 0) || undefined;
  const q = params.get("q") ?? "";
  const sort = (params.get("sort") as Sort) || "newest";

  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const filters = { category: category || undefined, source_type: source || undefined, min_impact: minImpact, q: q || undefined };
  const { data, error, isLoading, refetch, isFetching } = useSignals(filters);
  const all = useSignals({}); // unfiltered, for the summary strip

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const items = useMemo(() => {
    const rows = [...(data?.items ?? [])];
    if (sort === "impact") rows.sort((a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1) || b.published_at.localeCompare(a.published_at));
    return rows;
  }, [data, sort]);

  const threshold = meta?.trigger_threshold ?? 7;
  const everything = all.data?.items ?? [];
  const triggering = everything.filter((s) => (s.impact_score ?? 0) >= threshold).length;
  const partial = everything.filter((s) => s.status === "PARTIAL").length;
  const news = everything.filter((s) => s.source_type === "NEWS").length;
  const social = everything.length - news;
  const filtered = !!(category || source || minImpact || q);

  return (
    <>
      <PageHeader
        title="Risk Feed"
        sub="Every item is scored for sentiment, event type and market-impact proxy, with the evidence kept alongside. Open one to see why."
      />

      <div className="card card-pad mb-5 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="Signals" value={all.isLoading ? "–" : everything.length} sub={all.isLoading ? "" : `${news} news · ${social} social`} />
        <Stat label={`Impact ≥ ${threshold}`} value={all.isLoading ? "–" : triggering} sub="Trigger a stress test" tone="high" />
        <Stat label="Partial" value={all.isLoading ? "–" : partial} sub="Impact unavailable, not invented" />
        <Stat label="Replay clock" value={meta ? dateTime(meta.as_of).slice(-9, -4) : "–"} sub={meta ? `${dateTime(meta.as_of).slice(0, 6)} UTC · fixed for demos` : ""} />
      </div>

      <div className="mb-4 flex flex-col gap-3">
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0" role="group" aria-label="Filter by event type">
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
          <label className="relative min-w-[14rem] flex-1 sm:max-w-sm">
            <span className="sr-only">Search signals</span>
            <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
            <input className="field pl-9" type="search" placeholder="Search headline, company, ticker" value={q} onChange={(e) => set("q", e.target.value || null)} />
          </label>
          <div className="flex items-center gap-1.5" role="group" aria-label="Filter by source">
            {[["", "All sources"], ["NEWS", "News"], ["SOCIAL", "Social"]].map(([v, l]) => (
              <button key={v} type="button" className="chip" aria-pressed={source === v} onClick={() => set("source", v || null)}>
                {l}
              </button>
            ))}
          </div>
          <button type="button" className="chip" aria-pressed={minImpact === threshold} onClick={() => set("min", minImpact === threshold ? null : String(threshold))}>
            Impact ≥ {threshold}
          </button>
          <label className="ml-auto flex items-center gap-2 text-sm text-muted">
            Sort
            <select className="field !w-auto" value={sort} onChange={(e) => set("sort", e.target.value === "newest" ? null : e.target.value)}>
              <option value="newest">Newest</option>
              <option value="impact">Highest impact</option>
            </select>
          </label>
        </div>
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
            {items.map((s) => (
              <FeedRow key={s.id} s={s} asOf={meta?.as_of ?? s.published_at} label={label} />
            ))}
          </ul>
        )}
        {items.length > 0 && (
          <p className="flex items-center gap-1.5 px-4 py-2.5 text-xs text-muted">
            <Chevron size={12} /> {items.length} of {everything.length || items.length} signals shown. {meta?.profile === "replay" ? "Real documents, placeholder sentiment/event/impact (not model output)." : "All demo fixtures (fixture-v0), not model output."}
          </p>
        )}
      </section>
    </>
  );
}

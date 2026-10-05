import clsx from "clsx";
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { useLiveStatus, useMeta, useScenarios, useSignals } from "../api/hooks";
import { MiniChain } from "../components/assessment/MiniChain";
import type { EventCategory, Meta, SignalSummary } from "../api/types";
import { EVENT_CATEGORIES } from "../api/types";
import { Alert, ArrowRight, CATEGORY_ICON, Chevron, Search } from "../components/icons";
import { EmptyState, ErrorState, ImpactMeter, SentimentBar, Skeleton, SourceBadge, StatusTag } from "../components/ui";
import { EventStatusTag } from "../components/EventStatusTag";
import { StageStrip } from "../components/StageStrip";
import { LiveBar } from "../components/live/LiveBar";
import { ChannelTag, RelevanceTag, ScopeTag } from "../components/scope/Tags";
import { CHANNEL_LABEL, subjectLine, subjectOfSummary, type ScopeLevel } from "../lib/scope";
import { ago } from "../lib/format";
import { FEATURED, pickAlso, pickFeatured } from "../lib/featured";
import { impactIsModel, servedKinds, summaryKind } from "../lib/impact";
import { eventIsModel, sentimentIsModel } from "../lib/provenance";
import { categoryLabeler } from "../lib/taxonomy";

type Sort = "newest" | "impact";

function FeedRow({ s, asOf, label, baseline, assessed }: { s: SignalSummary; asOf: string; label: (c: string) => string; baseline: number | null; assessed: boolean }) {
  const unknown = s.scope_level === "UNRESOLVED";
  const isNew = baseline !== null && s.first_seq !== null && s.first_seq > baseline;
  const isUpdated = !isNew && baseline !== null && s.updated_seq !== null && s.updated_seq > baseline;
  // a live signal is read against the wall clock; the replay clock only describes replayed documents
  const now = s.channel === "REPLAY" ? asOf : new Date().toISOString();
  return (
    <li>
      <Link
        to={`/events/${s.id}`}
        className="group grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-2.5 border-b border-rule px-4 py-3.5 transition-colors duration-[var(--duration-fast)] hover:bg-paper-3 xl:grid-cols-[7.5rem_minmax(0,1fr)_9.5rem_3.75rem_4.25rem] xl:items-center"
      >
        <div className="pt-0.5 xl:pt-0">
          {assessed ? (
            <span className="flex flex-col gap-0.5">
              <ImpactMeter score={s.severity_score ?? null} noun="Severity" range={s.severity_low != null && s.severity_high != null && s.severity_low !== s.severity_high ? [s.severity_low, s.severity_high] : null} />
              {s.severity_score != null && <span className="text-2xs text-muted">{s.severity_band_label} · {s.extraction_mode === "LLM" ? "AI-assisted" : "rule-based"}</span>}
            </span>
          ) : (
            <ImpactMeter
              score={s.impact_score}
              kind={s.impact_score === null || s.data_origin === "DEMO_FIXTURE" ? undefined : summaryKind(s)}
              showKind={s.impact_score !== null && s.data_origin !== "DEMO_FIXTURE"}
            />
          )}
        </div>
        <div className="min-w-0">
          <p className="font-medium leading-snug text-ink group-hover:text-accent-strong">{s.headline}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            {s.scope_level === "COMPANY" ? (
              <>
                <span className="text-ink-2">{s.entity_name}</span>
                <span className="num">{s.ticker}</span>
                <span aria-hidden="true">·</span>
                <span>{s.sector}</span>
              </>
            ) : (
              <span className={unknown ? "text-warn" : "text-ink-2"}>{subjectLine(subjectOfSummary(s))}</span>
            )}
            <span aria-hidden="true">·</span>
            <SourceBadge type={s.source_type} name={s.source} />
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {assessed && s.assessed_category ? (
              <EventStatusTag status={s.assessed_category === "NO_EVENT" ? "NO_EVENT" : "CLASSIFIED"} category={(s.assessed_category === "NO_EVENT" ? s.category : s.assessed_category) as EventCategory} label={label} />
            ) : (
              <EventStatusTag status={s.event_status} category={s.category} label={label} />
            )}
            {!assessed && s.status === "PARTIAL" && s.event_status === "CLASSIFIED" && (
              <StatusTag tone="warn" icon={<Alert size={12} />}>Partial</StatusTag>
            )}
            {s.scope_level !== "COMPANY" && <ScopeTag level={s.scope_level as ScopeLevel} sector={s.scope_sector} strength={s.scope_strength} />}
            <ChannelTag channel={s.channel} />
            {s.relevance_level !== "NONE" && s.event_status !== "NO_EVENT" && <RelevanceTag level={s.relevance_level} share={s.relevance_share} />}
            {isNew && <StatusTag tone="ok">New</StatusTag>}
            {isUpdated && <StatusTag tone="ok">Updated · {s.source_count} reports</StatusTag>}
          </div>
        </div>
        <div className="col-span-2 flex flex-wrap items-center gap-x-4 gap-y-2 xl:contents">
          <SentimentBar score={s.sentiment_score} />
          <span className="num text-sm text-ink-2 xl:text-right" title="Sources reporting this narrative">
            {s.source_count}
            <span className="ml-1 text-xs text-muted xl:hidden">sources</span>
          </span>
          <span className="num text-xs text-muted xl:text-right">{ago(s.published_at, now)}</span>
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
function StoryStrip({ items, threshold, loading, assessed }: { items: SignalSummary[]; threshold: number; loading: boolean; assessed: boolean }) {
  const events = items.filter((s) => s.event_status === "CLASSIFIED");
  const notEvents = items.filter((s) => s.event_status === "NO_EVENT").length;
  const uncertain = items.filter((s) => s.event_status === "UNCERTAIN").length;
  const scored = items.filter((s) => s.impact_origin === "MODEL");
  const high = items.filter((s) => (s.impact_score ?? 0) >= threshold);
  const highModel = high.filter((s) => s.impact_origin === "MODEL").length;
  const n = (v: number) => (loading ? "–" : v.toLocaleString("en-US"));
  const sev = items.filter((s) => s.severity_score != null);
  const sevHigh = sev.filter((s) => (s.severity_score ?? 0) >= threshold);
  const legacy = [
    { k: "Read", v: n(items.length), t: "reports and posts", d: "Real news and social text, validated, de-duplicated and linked to companies." },
    { k: "Understand", v: n(events.length), t: "market events found", d: `NLP sets an event type and sentiment. ${loading ? "" : `${notEvents.toLocaleString("en-US")} were judged not to be events and ${uncertain} left uncertain.`}` },
    { k: "Estimate", v: n(scored.length), t: "scored by the impact model", d: "An experimental model rates how severe the reaction is likely to be. The rest keep a labelled rule or no score." },
    { k: "Stress", v: n(high.length), t: `reach impact ≥ ${threshold}`, d: `These trigger a scenario on the portfolio${loading ? "" : ` (${highModel} on model output, ${high.length - highModel} on the placeholder rule)`}.` },
  ];
  const current = [
    { k: "News", v: n(items.length), t: "reports and posts", d: "Real news and social text, validated, de-duplicated and linked to companies." },
    { k: "AI understanding", v: n(sev.length), t: "read as market events", d: `Event type, tone, sectors, regions and evidence quotes, checked against the text. ${loading ? "" : `${(items.length - sev.length).toLocaleString("en-US")} were not market events.`}` },
    { k: "Risk signal", v: n(sev.length), t: "scored for severity", d: "A transparent score from explicit weights. A triage level, not a forecast, and not validated." },
    { k: "Scenario → portfolio", v: n(sevHigh.length), t: `reach severity ≥ ${threshold}`, d: "These suggest a scenario that the deterministic engine applies to the portfolio; the rest can run as a what-if." },
  ];
  const steps = assessed ? current : legacy;
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

function FeaturedPanel({ items, label, assessed, threshold }: { items: SignalSummary[]; label: (c: string) => string; assessed: boolean; threshold: number }) {
  const scenarios = useScenarios();
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
          <span className="text-ink-2">{subjectLine(subjectOfSummary(hero))}</span>
          <EventStatusTag status={hero.event_status} category={hero.category} label={label} />
        </p>
        <p className="mt-3 max-w-[58ch] text-sm text-muted">{hero.id === FEATURED.hero.id ? FEATURED.hero.why : "The highest-impact model-scored event in this data."}</p>
      </div>
      <div className="flex flex-col items-start gap-4 sm:items-end">
        {assessed ? (
          <ImpactMeter score={hero.severity_score ?? null} noun="Severity" showLabel />
        ) : (
          <ImpactMeter score={hero.impact_score} kind={hero.impact_score === null ? undefined : summaryKind(hero)} showKind range={hero.impact_score_low != null && hero.impact_score_high != null ? [hero.impact_score_low, hero.impact_score_high] : null} />
        )}
        <Link to={`/events/${hero.id}`} className="btn btn-primary">
          Open the event story <ArrowRight size={14} />
        </Link>
      </div>
      {assessed && (
        <div className="col-span-full mt-2">
          <MiniChain
            s={hero}
            threshold={threshold}
            label={label}
            scenarioName={hero.assessed_category ? scenarios.data?.scenarios.find((x) => x.id === scenarios.data?.default_by_category[hero.assessed_category as keyof typeof scenarios.data.default_by_category])?.name : undefined}
            portfolioText={hero.relevance_share != null ? `${(hero.relevance_share * 100).toFixed(0)}% of the book reached` : undefined}
          />
        </div>
      )}
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
  const channel = params.get("channel") ?? "";
  const scope = params.get("scope") ?? "";
  const [shown, setShown] = useState(PAGE);
  const qc = useQueryClient();

  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const hasEventModel = eventIsModel(meta);
  const showNon = params.get("non") === "1" || !hasEventModel; // non-events are hidden by default once the model can say so
  const assessed = meta?.capabilities.assessment === true; // the headline number is the assessment's severity, not the trained model's impact
  const filters = {
    category: category || undefined, source_type: source || undefined, min_impact: minImpact, q: q || undefined,
    channel: channel || undefined, scope_level: scope || undefined,
  };
  const { data, error, isLoading, refetch, isFetching } = useSignals(filters);
  const all = useSignals({}); // unfiltered, for the story strip
  const live = useLiveStatus(meta?.profile === "replay", !!meta?.capabilities.live_enabled);
  // new arrivals are measured from the moment this page loaded; "N new" moves the line forward
  const [baseline, setBaseline] = useState<number | null>(null);
  useEffect(() => {
    if (baseline === null && all.data) setBaseline(all.data.seq);
  }, [all.data, baseline]);
  // the feed refetches when the live overlay's change counter moves, not on a timer of its own
  const liveSeq = live.data?.seq;
  useEffect(() => {
    if (liveSeq !== undefined) qc.invalidateQueries({ queryKey: ["signals"] });
  }, [liveSeq, qc]);

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
    setShown(PAGE);
  };

  const items = useMemo(() => {
    const isNon = (s: SignalSummary) => (assessed && s.assessed_category ? s.assessed_category === "NO_EVENT" : s.event_status === "NO_EVENT");
    const rows = (data?.items ?? []).filter((s) => (showNon || !isNon(s)) && (!scoredOnly || s.impact_origin === "MODEL"));
    const score = (s: SignalSummary) => (assessed ? s.severity_score : s.impact_score) ?? -1;
    if (sort === "impact") rows.sort((a, b) => score(b) - score(a) || b.published_at.localeCompare(a.published_at));
    return rows;
  }, [data, sort, showNon, scoredOnly, assessed]);

  const threshold = meta?.trigger_threshold ?? 7;
  const everything = all.data?.items ?? [];
  const processed = everything.filter((s) => s.channel !== "MANUAL"); // the strip describes the feed; one pasted text should not move it
  const filtered = !!(category || source || minImpact || q || scoredOnly || channel || scope);
  const hasOverlay = everything.some((s) => s.channel !== "REPLAY");
  const newCount = baseline === null ? 0 : everything.filter((s) => (s.updated_seq ?? 0) > baseline).length;
  const nonEvents = everything.filter((s) => (assessed && s.assessed_category ? s.assessed_category === "NO_EVENT" : s.event_status === "NO_EVENT")).length;
  const moreFilters = !!(category || source || sort !== "newest" || scope);

  return (
    <>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Risk Feed</h1>
        <p className="mt-1 max-w-[64ch] text-md text-ink-2">
          EventShock reads financial text, works out what happened and how severe it is likely to be, and shows what that does to a portfolio. Start with the featured event, or browse.
        </p>
      </header>

      {live.data && (
        <LiveBar
          st={live.data}
          newCount={newCount}
          onJumpNew={() => {
            setParams(new URLSearchParams(), { replace: true });
            if (all.data) setBaseline(all.data.seq);
            window.scrollTo({ top: 0 });
          }}
        />
      )}
      <StoryStrip items={processed} threshold={threshold} loading={all.isLoading} assessed={assessed} />
      {!all.isLoading && <FeaturedPanel items={everything} label={label} assessed={assessed} threshold={threshold} />}

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
            {assessed ? "Severity" : "Impact"} ≥ {threshold}
          </button>
          {impactIsModel(meta) && !assessed && (
            <button type="button" className="chip" aria-pressed={scoredOnly} onClick={() => set("scored", scoredOnly ? null : "1")}>
              Model-scored
            </button>
          )}
          {hasEventModel && (
            <button type="button" className="chip" aria-pressed={showNon} onClick={() => set("non", showNon ? null : "1")}>
              Show non-events{all.isLoading ? "" : ` (${nonEvents})`}
            </button>
          )}
          {hasOverlay &&
            (["LIVE", "MANUAL"] as const).map((c) => (
              <button key={c} type="button" className="chip" aria-pressed={channel === c} onClick={() => set("channel", channel === c ? null : c)}>
                {CHANNEL_LABEL[c]} only
              </button>
            ))}
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
            <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by what the signal is about">
              {(["COMPANY", "SECTOR", "MARKET", "UNRESOLVED"] as const).map((l) => (
                <button key={l} type="button" className="chip" aria-pressed={scope === l} onClick={() => set("scope", scope === l ? null : l)}>
                  {l === "COMPANY" ? "Company" : l === "SECTOR" ? "Sector" : l === "MARKET" ? "Market-wide" : "Unresolved"}
                </button>
              ))}
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
                  <option value="impact">{assessed ? "Highest severity" : "Highest impact"}</option>
                </select>
              </label>
            </div>
          </div>
        </details>
      </div>

      <section className="card overflow-hidden" aria-busy={isFetching} aria-label="Risk signals">
        <div className="hidden grid-cols-[7.5rem_minmax(0,1fr)_9.5rem_3.75rem_4.25rem] gap-x-4 border-b border-rule px-4 py-2 xl:grid" aria-hidden="true">
          {[assessed ? "Severity" : "Impact", "Event", "Sentiment", "Sources", "Seen"].map((h, i) => (
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
              <FeedRow key={s.id} s={s} asOf={meta?.as_of ?? s.published_at} label={label} baseline={baseline} assessed={assessed} />
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

import clsx from "clsx";
import { Link, useParams } from "react-router-dom";
import { useMeta, useScenarios, useSentimentModel, useSignal } from "../api/hooks";
import type { EventCategory, RiskSignal } from "../api/types";
import { EVENT_CATEGORIES } from "../api/types";
import { Alert, ArrowLeft, ArrowRight, Check, Info } from "../components/icons";
import {
  Card,
  CategoryTag,
  ErrorState,
  ImpactMeter,
  InlineNote,
  Loading,
  SourceBadge,
  Stat,
  StackBar,
  StatusTag,
} from "../components/ui";
import { ago, dateTime, signed } from "../lib/format";
import { categoryLabeler } from "../lib/taxonomy";
import { isPlaceholder, originChip, originLabel, relationNote, ruleNote, stageKind, stageKindText, stageName, timestampNote } from "../lib/provenance";
import { sentimentLabel, severityBand } from "../lib/severity";

function ImpactCard({ s, threshold }: { s: RiskSignal; threshold: number }) {
  const scenarios = useScenarios();
  const scenarioId = scenarios.data?.default_by_category[s.event.category];
  const scenario = scenarios.data?.scenarios.find((x) => x.id === scenarioId);
  const impact = s.impact;
  const band = impact ? severityBand(impact.score) : null;
  const maxAbs = Math.max(0.01, ...(impact?.drivers.map((d) => Math.abs(d.contribution)) ?? [0]));
  const triggers = !!impact && impact.score >= threshold;

  return (
    <Card title="Impact assessment" aside="Market-response proxy, 1 to 10" className="h-full">
      {!impact ? (
        <InlineNote tone="warn" title="Impact unavailable for this signal">
          {s.status_reason} EventShock never substitutes a default score, so this signal cannot trigger a stress test.
        </InlineNote>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
            <ImpactMeter score={impact.score} size="lg" />
            <div className="pb-1">
              <p className={clsx("font-display text-lg font-semibold", band?.text)}>{band?.label} impact</p>
              <p className="num text-xs text-muted">
                raw {impact.raw.toFixed(2)} → {impact.quantisation}
              </p>
            </div>
          </div>
          <p className="mt-3 max-w-[60ch] text-sm text-muted">
            An estimate of how large a market reaction this event is likely to cause. It is not a probability of loss and not a price forecast.
          </p>

          <h3 className="mt-6 mb-2 flex flex-wrap items-baseline justify-between gap-2 text-sm font-semibold">
            What drives the score
            <StatusTag tone="demo">{isPlaceholder(s) ? "Placeholder heuristic · not a trained model" : "Fixture drivers · illustrative, not SHAP"}</StatusTag>
          </h3>
          <ul className="space-y-2">
            {impact.drivers.map((d) => (
              <li key={d.feature} className="grid grid-cols-[minmax(0,1fr)_7.5rem_3.25rem] items-center gap-3 sm:grid-cols-[minmax(0,1.3fr)_9rem_3.5rem]">
                <span className="min-w-0 text-sm text-ink-2" title={d.note}>
                  {d.feature}
                  {d.note && <span className="block text-xs text-muted">{d.note}</span>}
                </span>
                <span className="relative h-2 rounded-sm bg-paper-4" aria-hidden="true">
                  <span className="absolute inset-y-0 left-1/2 w-px bg-faint" />
                  <span
                    className={clsx("absolute inset-y-0 rounded-sm", d.contribution >= 0 ? "bg-sev-high" : "bg-sev-low")}
                    style={d.contribution >= 0 ? { left: "50%", width: `${(d.contribution / maxAbs) * 50}%` } : { right: "50%", width: `${(Math.abs(d.contribution) / maxAbs) * 50}%` }}
                  />
                </span>
                <span className={clsx("num text-right text-sm", d.contribution >= 0 ? "text-sev-high" : "text-sev-low")}>
                  {signed(d.contribution)}
                </span>
              </li>
            ))}
          </ul>

          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-rule pt-5">
            <div className="min-w-0 text-sm">
              <p className="flex items-center gap-2 font-medium">
                {triggers ? <Check size={15} className="text-sev-high" /> : <Info size={15} className="text-muted" />}
                {triggers ? `Meets the trigger threshold (≥ ${threshold})` : `Below the trigger threshold (≥ ${threshold})`}
              </p>
              <p className="mt-1 text-muted">
                {scenario ? (
                  <>
                    Maps to <span className="text-ink-2">{scenario.name}</span>, an illustrative template.
                  </>
                ) : (
                  "Scenario mapping loading…"
                )}
              </p>
            </div>
            <Link to={`/stress?signal=${s.id}${triggers ? "&run=1" : ""}`} className={clsx("btn", triggers && "btn-primary")}>
              {triggers ? "Run stress test" : "Run as what-if"} <ArrowRight size={14} />
            </Link>
          </div>
        </>
      )}
    </Card>
  );
}

function EventTypeCard({ s, label }: { s: RiskSignal; label: (c: string) => string }) {
  const rows = EVENT_CATEGORIES.map((c) => ({ c, p: s.event.probabilities[c as EventCategory] ?? 0 })).sort((a, b) => b.p - a.p);
  return (
    <Card
      title="Event type"
      aside={s.provenance && stageKind(s.provenance.stage_origins.event) !== "model" ? <StatusTag tone="warn">Placeholder rules</StatusTag> : "What happened"}
    >
      <ul className="space-y-1.5">
        {rows.map(({ c, p }, i) => (
          <li key={c} className="grid grid-cols-[minmax(0,1fr)_6rem_2.75rem] items-center gap-3 text-sm">
            <span className={clsx("truncate", i === 0 ? "font-medium text-ink" : "text-muted")}>{label(c)}</span>
            <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
              <span className={clsx("block h-full rounded-sm", i === 0 ? "bg-accent" : "bg-faint")} style={{ width: `${p * 100}%` }} />
            </span>
            <span className={clsx("num text-right", i === 0 ? "text-ink" : "text-muted")}>{(p * 100).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SentimentCard({ s }: { s: RiskSignal }) {
  const { positive, neutral, negative, score } = s.sentiment;
  const audit = s.provenance?.sentiment;
  const isModel = stageKind(s.provenance?.stage_origins.sentiment) === "model" && !!audit;
  const { data: card } = useSentimentModel(isModel);
  const held = card?.evaluations.find((e) => e.id === "tfn_test")?.model;
  const own = card?.evaluations.find((e) => e.id === "gold_history")?.model;
  return (
    <Card
      title="Sentiment"
      aside={
        isModel ? (
          <StatusTag tone="ok" icon={<Check size={12} />}>Trained model</StatusTag>
        ) : s.provenance ? (
          <StatusTag tone="warn">{stageKindText(s.provenance.stage_origins.sentiment)}</StatusTag>
        ) : (
          "How it is framed"
        )
      }
    >
      <div className="mb-4 flex items-baseline gap-3">
        <span className={clsx("num text-3xl font-medium", score < -0.15 ? "text-neg" : score > 0.15 ? "text-pos" : "text-ink-2")}>
          {score > 0 ? "+" : score < 0 ? "−" : ""}
          {Math.abs(score).toFixed(2)}
        </span>
        <span className="text-sm text-muted">{sentimentLabel(score)} · positive − negative, range −1 to +1</span>
      </div>
      <StackBar
        parts={[
          { label: "Negative", value: negative, className: "bg-neg" },
          { label: "Neutral", value: neutral, className: "bg-neu" },
          { label: "Positive", value: positive, className: "bg-pos" },
        ]}
      />
      {isModel && audit && (
        <div className="mt-4 space-y-3">
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
            <dt className="text-muted">Model</dt>
            <dd className="num">{audit.model_id}</dd>
            <dt className="text-muted">Confidence</dt>
            <dd className="num">
              {(audit.confidence * 100).toFixed(0)}% <span className="font-sans text-muted">in its top class, calibrated</span>
            </dd>
          </dl>
          {audit.seen_in_training && (
            <InlineNote tone="warn" title="In-sample: the model trained on this exact text">
              This post is in the dataset the model learned from, so its score here is not evidence of accuracy.
            </InlineNote>
          )}
        </div>
      )}
      <p className="mt-3 text-xs text-muted">
        {isModel
          ? held
            ? `A text model, not a judgement. On held-out Twitter Financial News posts it scores macro-F1 ${held.macro_f1.toFixed(2)}${own ? `; on our own AI-labelled sources only ${own.macro_f1.toFixed(2)}, so read scores from our sources as indicative.` : "."}`
            : "A trained text model, not a judgement. Tone only."
          : "Sentiment is tone only. A neutral regulatory notice can matter more than a loud opinion."}
      </p>
    </Card>
  );
}

function EvidenceCard({ s, asOf }: { s: RiskSignal; asOf: string }) {
  const e = s.evidence;
  return (
    <Card title="Evidence" aside="Observable corroboration, kept separate">
      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
        <Stat label="Sources" value={e.source_count} sub={`${e.unique_domain_count} unique outlets`} />
        <Stat label="Recent mentions" value={e.recent_mention_count} sub={`${e.coverage_velocity.toFixed(1)} per hour`} />
        <Stat label="Novelty" value={e.novelty_score.toFixed(2)} sub="0 repeat · 1 new" />
        <Stat label="Model confidence" value={e.model_confidence.toFixed(2)} sub="Not truth, a model property" />
      </div>
      {e.contradicted_by.length > 0 && (
        <div className="mt-5">
          <InlineNote tone="warn" title="Contradicted by another report">
            Both are preserved; neither is silently discarded.{" "}
            {e.contradicted_by.map((id) => (
              <Link key={id} to={`/events/${id}`} className="font-medium text-accent underline underline-offset-2">
                Open {id}
              </Link>
            ))}
          </InlineNote>
        </div>
      )}
      <h3 className="mt-6 mb-2 text-sm font-semibold">Corroborating coverage</h3>
      {e.corroborating.length === 0 ? (
        <p className="text-sm text-muted">No other source carried this narrative. Treat it as unconfirmed.</p>
      ) : (
        <ul className="divide-y divide-rule border-y border-rule">
          {e.corroborating.map((c) => (
            <li key={c.url ?? c.headline} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 text-sm">
              <span className="min-w-0 flex-1 basis-60 text-ink-2">{c.headline}</span>
              <span className="flex items-center gap-3 text-xs">
                <span className="text-muted" title={c.relation}>{relationNote(c.relation)}</span>
                <SourceBadge type={c.source_type} name={c.source} />
                <span className="num text-muted">{ago(c.published_at, asOf)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function ProvenanceCard({ s }: { s: RiskSignal }) {
  const p = s.provenance;
  if (!p) return null;
  const ea = p.entity_audit;
  const d = p.dedup;
  return (
    <Card title="Provenance" aside="What happened before this screen">
      <ol className="space-y-3 text-xs">
        <li>
          <p className="font-medium text-ink">1 · Source record</p>
          <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1">
            <dt className="text-muted">Adapter</dt>
            <dd className="num">{p.adapter}</dd>
            <dt className="text-muted">Snapshot</dt>
            <dd className="num">{p.snapshot_id}</dd>
            <dt className="text-muted">Record</dt>
            <dd className="num">{p.record_ref}</dd>
            <dt className="text-muted">sha256</dt>
            <dd className="num break-all">{p.content_sha256.slice(0, 16)}…</dd>
            <dt className="text-muted">Time is</dt>
            <dd>{timestampNote(p.timestamp_origin)}</dd>
          </dl>
        </li>
        <li>
          <p className="font-medium text-ink">2 · Entity resolution</p>
          <p className="mt-1 text-ink-2">
            {ruleNote(ea.rule)}
            {ea.matched_text ? <> · matched <span className="num">{ea.matched_text}</span></> : null}
            {ea.multi_entity ? " · several companies mentioned, confidence capped" : ""}
          </p>
          {ea.candidates.length > 1 && (
            <p className="mt-1 text-muted">
              Also considered: {ea.candidates.slice(1).map((c) => `${c.entity_name} (${c.matched_text})`).join(", ")}
            </p>
          )}
          {ea.rejected.length > 0 && (
            <p className="mt-1 text-warn">
              Refused: {ea.rejected.map((r) => `${r.matched_text} (${r.reason})`).join("; ")}
            </p>
          )}
          {ea.unmatched_cashtags.length > 0 && (
            <p className="mt-1 text-muted">Not in the entity master: {ea.unmatched_cashtags.map((t) => `$${t}`).join(" ")}</p>
          )}
        </li>
        <li>
          <p className="font-medium text-ink">3 · De-duplication</p>
          <p className="mt-1 text-ink-2">
            {d.member_count} distinct report{d.member_count === 1 ? "" : "s"} in this story
            {d.exact_duplicates_folded > 0 ? ` · ${d.exact_duplicates_folded} exact duplicate${d.exact_duplicates_folded === 1 ? "" : "s"} folded away` : ""}
          </p>
          <p className="num mt-1 text-muted">{d.cluster_id}</p>
        </li>
        <li>
          <p className="font-medium text-ink">4 · Enrichment</p>
          <ul className="mt-1 space-y-1 text-ink-2">
            {(["sentiment", "event", "impact"] as const).map((k) => (
              <li key={k} className="flex flex-wrap items-baseline gap-x-2">
                <span className="w-20 shrink-0 text-muted">{stageName(k)}</span>
                <span className={stageKind(p.stage_origins[k]) === "model" ? "text-pos" : "text-warn"}>{stageKindText(p.stage_origins[k])}</span>
                {k === "sentiment" && p.sentiment && (
                  <span className="num text-muted">
                    {p.sentiment.model_id} · {p.sentiment.artifact_sha256.slice(0, 8)}
                    {p.sentiment.seen_in_training ? " · in-sample" : ""}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </li>
      </ol>
    </Card>
  );
}

export function EventPage() {
  const { id } = useParams();
  const { data: s, error, isLoading, refetch } = useSignal(id);
  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);

  return (
    <>
      <Link to="/" className="btn btn-ghost mb-4 -ml-3">
        <ArrowLeft size={14} /> Risk Feed
      </Link>
      {isLoading && <Loading label="Loading event" />}
      {error && (
        <ErrorState
          error={error.message.includes("not found") ? new Error(`No event with id “${id}”. It may belong to a different data profile.`) : error}
          retry={() => refetch()}
        />
      )}
      {s && (
        <>
          <header className="mb-6">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <CategoryTag category={s.event.category} label={label(s.event.category)} />
              <SourceBadge type={s.document.source_type} name={s.document.source} />
              <span className="num text-xs text-muted">{dateTime(s.document.published_at)}</span>
              {s.provenance?.timestamp_origin === "SYNTHETIC_REPLAY_CLOCK" && (
                <span className="text-xs text-warn" title={timestampNote("SYNTHETIC_REPLAY_CLOCK")}>replay time, not original</span>
              )}
              {s.status === "PARTIAL" && <StatusTag tone="warn" icon={<Alert size={12} />}>Partial signal</StatusTag>}
              <StatusTag tone="demo">{originChip(s.data_origin)}</StatusTag>
            </div>
            <h1 className="max-w-[28ch] text-2xl font-semibold sm:max-w-[36ch] sm:text-3xl">{s.document.headline}</h1>
            <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted">
              {s.entity.entity_id === "UNKNOWN_ENTITY" ? (
                <span className="text-warn">Entity unresolved. No company could be linked, so only market-wide shocks would apply.</span>
              ) : (
                <>
                  <span className="font-medium text-ink">{s.entity.entity_name}</span>
                  <span className="num">{s.entity.ticker}</span>
                  <span>{s.entity.sector}</span>
                  <span>{s.entity.country}</span>
                  <span>link confidence {(s.entity.link_confidence * 100).toFixed(0)}%</span>
                </>
              )}
            </p>
          </header>

          <div className="grid gap-5 lg:grid-cols-12">
            <div className="lg:col-span-7">
              <ImpactCard s={s} threshold={meta?.trigger_threshold ?? 7} />
            </div>
            <div className="flex flex-col gap-5 lg:col-span-5">
              <SentimentCard s={s} />
              <EventTypeCard s={s} label={label} />
            </div>
            <div className="lg:col-span-7">
              <EvidenceCard s={s} asOf={meta?.as_of ?? s.created_at} />
            </div>
            <div className="flex flex-col gap-5 lg:col-span-5">
              <Card title="Source text" aside={s.document.source_type === "NEWS" ? "News" : "Social post"}>
                {s.document.body ? (
                  <p className="text-sm leading-relaxed text-ink-2">{s.document.body}</p>
                ) : (
                  <p className="text-sm text-muted">{s.document.source_type === "SOCIAL" ? "The post text is the heading above." : "Headline only: this source supplies no article text."}</p>
                )}
                <dl className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-xs">
                  <dt className="text-muted">Author</dt>
                  <dd>{s.document.author ?? "Not attributed"}</dd>
                  <dt className="text-muted">Published</dt>
                  <dd className="num">{dateTime(s.document.published_at)}</dd>
                  <dt className="text-muted">Ingested</dt>
                  <dd className="num">{dateTime(s.document.ingested_at)}</dd>
                  <dt className="text-muted">URL</dt>
                  <dd className="num break-all text-muted">
                    {s.document.url?.startsWith("https://") && s.data_origin !== "DEMO_FIXTURE" ? (
                      <a href={s.document.url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-2 hover:text-ink">
                        {s.document.url}
                      </a>
                    ) : (
                      (s.document.url ?? "None")
                    )}
                  </dd>
                </dl>
              </Card>
              {s.provenance && <ProvenanceCard s={s} />}
              <Card title="Audit" aside="Reproducibility">
                <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-xs">
                  <dt className="text-muted">Signal</dt>
                  <dd className="num">{s.id}</dd>
                  <dt className="text-muted">Data origin</dt>
                  <dd>{originLabel(s.data_origin)}</dd>
                  <dt className="text-muted">Sentiment model</dt>
                  <dd className="num">{s.model_versions.sentiment}</dd>
                  {s.provenance?.sentiment && (
                    <>
                      <dt className="text-muted">Sentiment artifact</dt>
                      <dd className="num break-all">sha256 {s.provenance.sentiment.artifact_sha256.slice(0, 16)}…</dd>
                    </>
                  )}
                  <dt className="text-muted">Event model</dt>
                  <dd className="num">{s.model_versions.event}</dd>
                  <dt className="text-muted">Impact model</dt>
                  <dd className="num">{s.model_versions.impact ?? "unavailable"}</dd>
                  <dt className="text-muted">Entity resolver</dt>
                  <dd className="num">{s.model_versions.entity_resolver}</dd>
                  <dt className="text-muted">Created</dt>
                  <dd className="num">{dateTime(s.created_at)}</dd>
                </dl>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}

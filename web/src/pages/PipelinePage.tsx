import { usePipelineReport, useMeta } from "../api/hooks";
import { SentimentModelPanel } from "../components/SentimentModelPanel";
import { Card, EmptyState, ErrorState, Loading, PageHeader, Stat, StatusTag } from "../components/ui";
import { dateTime } from "../lib/format";
import { sentimentIsModel, stageKind } from "../lib/provenance";

export function PipelinePage() {
  const { data: meta } = useMeta();
  const enabled = !!meta?.replay;
  const { data: r, error, isLoading, refetch } = usePipelineReport(enabled);

  if (meta && !meta.replay) {
    return (
      <EmptyState title="No pipeline in the demo profile">
        This profile serves hand-authored fixtures. Start with the default replay profile to see the ingestion pipeline.
      </EmptyState>
    );
  }
  if (error) return <ErrorState error={error} retry={() => refetch()} />;
  if (isLoading || !r) return <Loading label="Loading pipeline report" />;

  const c = r.counts;
  const funnel = [
    { label: "Records read", value: c.records_read, sub: "every line of every source file" },
    { label: "Quarantined", value: c.quarantined, sub: "rejected with a reason code" },
    { label: "Exact duplicates folded", value: c.exact_duplicates_folded, sub: "same article / same text, same outlet" },
    { label: "Reports kept", value: c.reports_in_signals, sub: "distinct reports inside signals" },
    { label: "Signals", value: c.signals, sub: "one per story" },
  ];

  return (
    <>
      <PageHeader
        title="Data pipeline"
        sub={
          <>
            Snapshot <span className="num">{r.snapshot_id}</span> · replay clock <span className="num">{dateTime(r.replay_as_of)}</span> · no network at runtime
          </>
        }
      />
      <div className="grid gap-5 lg:grid-cols-12">
        <div className="lg:col-span-12">
          <Card title="From records to signals" aside="Every record ends in exactly one place">
            <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
              {funnel.map((f) => (
                <Stat key={f.label} label={f.label} value={f.value} sub={f.sub} />
              ))}
            </div>
            <p className="num mt-4 text-xs text-muted">
              {c.records_read} read = {c.quarantined} quarantined + {c.exact_duplicates_folded} folded + {c.reports_in_signals} kept
            </p>
          </Card>
        </div>

        <div className="lg:col-span-7">
          <Card title="Sources" aside="Provenance and licence">
            <ul className="divide-y divide-rule">
              {r.sources.map((s) => (
                <li key={s.name} className="py-3 text-sm first:pt-0 last:pb-0">
                  <p className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium">{s.name}</span>
                    <StatusTag tone="demo">{s.source_type === "NEWS" ? "News" : "Social"}</StatusTag>
                  </p>
                  <p className="num mt-1 text-xs text-muted">
                    {s.records} records · {s.quarantined} quarantined · {s.exact_duplicates_folded} folded · {s.signals} signals
                  </p>
                  <p className="mt-1 text-xs text-ink-2">{s.attribution}</p>
                  <p className="mt-1 text-xs text-muted">Licence: {s.license}</p>
                  <p className="mt-1 text-xs text-muted">{s.notes}</p>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="flex flex-col gap-5 lg:col-span-5">
          <Card title="Quarantine" aside="Nothing is dropped silently">
            {Object.keys(r.quarantine_by_code).length === 0 ? (
              <p className="text-sm text-muted">No records were quarantined.</p>
            ) : (
              <ul className="divide-y divide-rule border-y border-rule text-sm">
                {Object.entries(r.quarantine_by_code).map(([code, n]) => (
                  <li key={code} className="flex justify-between py-2">
                    <span className="num">{code}</span>
                    <span className="num text-muted">{n}</span>
                  </li>
                ))}
              </ul>
            )}
            {r.quarantine_sample.length > 0 && (
              <details className="mt-3 text-xs">
                <summary className="cursor-pointer text-muted">Sample of rejected records</summary>
                <ul className="mt-2 space-y-2">
                  {r.quarantine_sample.slice(0, 12).map((q) => (
                    <li key={`${q.source}-${q.record_ref}`}>
                      <span className="num">{q.code}</span> · <span className="num text-muted">{q.record_ref}</span>
                      <span className="block text-muted">{q.detail}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </Card>
          <Card title="Entities and duplicates">
            <div className="grid grid-cols-2 gap-x-6 gap-y-4">
              <Stat label="Resolved to a company" value={c.entity_resolved} sub="signals" />
              <Stat label="Unresolved" value={c.entity_unknown} sub="market-wide shocks only" />
              <Stat label="Ambiguous mentions refused" value={c.rejected_ambiguous_mentions} sub="e.g. a fruit, a travel visa" />
              <Stat label="Multi-company texts" value={c.multi_entity} sub="confidence capped" />
              <Stat label="Syndicated copies" value={c.syndicated} sub="same text, other outlet" />
              <Stat label="Near-duplicates / same event" value={`${c.near_duplicates} / ${c.same_event}`} sub="folded into one signal" />
            </div>
          </Card>
        </div>

        {sentimentIsModel(meta) && (
          <div className="min-w-0 lg:col-span-12">
            <SentimentModelPanel enabled />
          </div>
        )}

        {r.fetch_log.length > 0 && (
          <div className="lg:col-span-12">
            <Card
              title="How the snapshot was downloaded"
              aside={`${r.fetch_log.filter((q) => q.status === "ok").length} of ${r.fetch_log.length} requests succeeded`}
            >
              <ul className="divide-y divide-rule border-y border-rule text-xs">
                {r.fetch_log.map((q) => (
                  <li key={q.query} className="grid grid-cols-[3.5rem_minmax(0,1fr)_auto] items-baseline gap-x-3 py-2">
                    <span className={q.status === "ok" ? "text-pos" : "font-medium text-warn"}>{q.status === "ok" ? "OK" : "FAILED"}</span>
                    <span className="num min-w-0 break-words text-ink-2">
                      {q.query}
                      {q.status !== "ok" && <span className="block text-muted">{q.last_error}</span>}
                    </span>
                    <span className="num text-muted">
                      {q.status === "ok" ? `${q.added} new / ${q.returned}` : "not fetched"} · {q.attempts} attempt{q.attempts === 1 ? "" : "s"}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted">
                A failed request is a gap in the data, not an error in it: the pack is partial and says so. The log is the full history, including the first per-issuer plan that was abandoned after rate-limit and query-length errors (see the project journey). Re-running the fetch retries only the failed requests of the current plan.
              </p>
            </Card>
          </div>
        )}

        <div className="lg:col-span-12">
          <Card title="What is real and what is a stand-in" aside={`${r.pipeline_version} · ${r.enrichment_version}`}>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
              {Object.entries(r.stage_origins).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k.replace("_", " ")}</dt>
                  <dd className={stageKind(v) === "model" ? "text-pos" : v.startsWith("PLACEHOLDER") ? "text-warn" : ""}>{v}</dd>
                </div>
              ))}
            </dl>
            <p className="num mt-4 break-all text-xs text-muted">Output digest (identical digest = identical replay): {r.output_digest}</p>
          </Card>
        </div>
      </div>
    </>
  );
}

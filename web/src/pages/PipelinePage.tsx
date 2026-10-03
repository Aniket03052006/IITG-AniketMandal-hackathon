import type { ReactNode } from "react";
import { usePipelineReport } from "../api/hooks";
import { PipelineFlow } from "../components/evidence/PipelineFlow";
import { ErrorState, Loading, Stat, StatusTag } from "../components/ui";
import { dateTime } from "../lib/format";
import { stageKind } from "../lib/provenance";

function Expand({ title, aside, children }: { title: string; aside?: string; children: ReactNode }) {
  return (
    <details className="expand">
      <summary>
        <span className="font-medium text-ink">{title}</span>
        {aside && <span className="text-sm text-muted">{aside}</span>}
      </summary>
      <div className="expand-body">{children}</div>
    </details>
  );
}

/** "How it is built": the pipeline as one picture, with the audit detail (quarantine, sources, download log) behind expanders. */
export function PipelineView() {
  const { data: r, error, isLoading, refetch } = usePipelineReport(true);
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
    <div>
      <p className="mb-5 max-w-[70ch] text-ink-2">
        Every record ends in exactly one place. Snapshot <span className="num">{r.snapshot_id}</span> · replay clock <span className="num">{dateTime(r.replay_as_of)}</span> · no network at run time, so a replay is the same every time.
      </p>
      <PipelineFlow r={r} />

      <div className="expands">
        <Expand title="From records to signals" aside={`${c.records_read} read = ${c.quarantined} quarantined + ${c.exact_duplicates_folded} folded + ${c.reports_in_signals} kept`}>
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
            {funnel.map((f) => (
              <Stat key={f.label} label={f.label} value={f.value} sub={f.sub} />
            ))}
          </div>
        </Expand>

        <Expand title="Sources, provenance and licences" aside={`${r.sources.length} sources`}>
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
        </Expand>

        <Expand title="Quarantine" aside="nothing is dropped silently">
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
            <details className="disclosure mt-3 text-xs">
              <summary>Sample of rejected records</summary>
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
        </Expand>

        <Expand title="Entities and duplicates">
          <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat label="Resolved to a company" value={c.entity_resolved} sub="signals" />
            <Stat label="Unresolved" value={c.entity_unknown} sub="market-wide shocks only" />
            <Stat label="Ambiguous mentions refused" value={c.rejected_ambiguous_mentions} sub="e.g. a fruit, a travel visa" />
            <Stat label="Multi-company texts" value={c.multi_entity} sub="confidence capped" />
            <Stat label="Syndicated copies" value={c.syndicated} sub="same text, other outlet" />
            <Stat label="Near-duplicates / same event" value={`${c.near_duplicates} / ${c.same_event}`} sub="folded into one signal" />
          </div>
        </Expand>

        {r.fetch_log.length > 0 && (
          <Expand title="How the snapshot was downloaded" aside={`${r.fetch_log.filter((q) => q.status === "ok").length} of ${r.fetch_log.length} requests succeeded`}>
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
              A failed request is a gap in the data, not an error in it: the pack would be partial and say so. This lists the requests of the current plan only.
              {r.superseded_requests > 0 && (
                <>
                  {" "}
                  {r.superseded_requests} request{r.superseded_requests === 1 ? "" : "s"} of an earlier, abandoned plan (per-issuer queries that hit rate limits, a too-short phrase and an over-long query) {r.superseded_requests === 1 ? "is" : "are"} left out here
                  because the sector queries replaced them; the full attempt log stays in the snapshot manifest.
                </>
              )}{" "}
              Re-running the fetch retries only the failed requests of the current plan.
            </p>
          </Expand>
        )}

        <Expand title="What is real and what is a stand-in" aside={`${r.pipeline_version} · ${r.enrichment_version}`}>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
            {Object.entries(r.stage_origins).map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-muted">{k.replace("_", " ")}</dt>
                <dd className={stageKind(v) === "model" ? "text-pos" : v.startsWith("PLACEHOLDER") ? "text-warn" : ""}>{v}</dd>
              </div>
            ))}
          </dl>
          <p className="num mt-4 break-all text-xs text-muted">Output digest (identical digest = identical replay): {r.output_digest}</p>
        </Expand>
      </div>
    </div>
  );
}



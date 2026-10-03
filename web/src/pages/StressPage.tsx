import clsx from "clsx";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMeta, usePortfolioExposure, usePortfolioSummary, useScenarios, useSignal, useSignals, useStressTest } from "../api/hooks";
import type { ExposureRow, StressResult } from "../api/types";
import { ArrowRight, Play, Spinner } from "../components/icons";
import { AuditPanel, Breakdown, PositionsTable, ResultHero, ShocksTable, TopPositions } from "../components/stress";
import { impactKind, summaryKind } from "../lib/impact";
import { Card, CategoryTag, EmptyState, ErrorState, ImpactMeter, InlineNote, Loading, Notice, PageHeader, Stat, StatusTag } from "../components/ui";
import { ASSET_CLASS_LABEL, money, pct } from "../lib/format";
import { categoryLabeler } from "../lib/taxonomy";

function ExposureBars({ rows, labelFn }: { rows: ExposureRow[]; labelFn?: (r: ExposureRow) => string }) {
  const max = Math.max(...rows.map((r) => r.share), 0.0001);
  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_4.5rem] items-center gap-3 text-sm">
          <span className="truncate text-ink-2">{labelFn ? labelFn(r) : r.label}</span>
          <span className="h-2 rounded-sm bg-paper-4" aria-hidden="true">
            <span className="block h-full rounded-sm bg-faint" style={{ width: `${(r.share / max) * 100}%` }} />
          </span>
          <span className="num text-right text-muted">{pct(r.share, 1)}</span>
        </li>
      ))}
    </ul>
  );
}

function PortfolioGlance() {
  const summary = usePortfolioSummary();
  const exposure = usePortfolioExposure();
  if (summary.error) return <ErrorState error={summary.error} retry={() => summary.refetch()} />;
  const s = summary.data;
  const e = exposure.data;
  return (
    <Card title="The portfolio being stressed" aside={<StatusTag tone="demo">Synthetic</StatusTag>}>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <Stat label="Total value" value={s ? money(s.total_value) : "–"} sub={s?.base_currency} />
        <Stat label="Positions" value={s?.asset_count ?? "–"} sub="Equities, bonds, loans, derivatives" />
        <Stat label="Issuers" value={s?.entity_count ?? "–"} />
      </div>
      {s && <p className="mt-3 text-xs text-muted">{s.description}</p>}
      {e && (
        <div className="mt-5 grid gap-6 md:grid-cols-2">
          <div>
            <h3 className="mb-2 text-sm font-semibold">By asset class</h3>
            <ExposureBars rows={e.by_asset_class} labelFn={(r) => ASSET_CLASS_LABEL[r.key] ?? r.label} />
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">By sector</h3>
            <ExposureBars rows={e.by_sector} />
          </div>
        </div>
      )}
    </Card>
  );
}

export function StressPage() {
  const [params, setParams] = useSearchParams();
  const signalId = params.get("signal") ?? "";
  const scenarioParam = params.get("scenario") ?? "";
  const wantRun = params.get("run") === "1";

  const { data: meta } = useMeta();
  const label = categoryLabeler(meta);
  const signals = useSignals({});
  const signal = useSignal(signalId || undefined);
  const scenarios = useScenarios();
  const exposure = usePortfolioExposure();
  const stress = useStressTest();

  const [whatIf, setWhatIf] = useState(false);
  const [impact, setImpact] = useState(7);
  const autoRan = useRef<string>("");

  const s = signal.data;
  const threshold = meta?.trigger_threshold ?? 7;
  const defaultScenarioId = s ? scenarios.data?.default_by_category[s.event.category] : undefined;
  const scenarioId = scenarioParam || defaultScenarioId || "";
  const selectedScenario = scenarios.data?.scenarios.find((x) => x.id === scenarioId);
  const entityNames = useMemo(() => new Map((exposure.data?.by_entity ?? []).map((r) => [r.key, r.label])), [exposure.data]);

  // Reset local state when the chosen event changes.
  useEffect(() => {
    stress.reset();
    setWhatIf(false);
    if (s?.impact) setImpact(s.impact.score);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signalId, s?.id]);

  const run = (opts: { force?: boolean } = {}) => {
    if (!signalId) return;
    const force = opts.force || whatIf;
    stress.mutate({
      signal_id: signalId,
      scenario_id: scenarioParam || undefined,
      force,
      impact_override: whatIf ? impact : undefined,
    });
  };

  // Arriving from "Run stress test" on an event: run once, then drop the flag from the URL.
  useEffect(() => {
    if (wantRun && s && autoRan.current !== s.id) {
      autoRan.current = s.id;
      stress.mutate({ signal_id: s.id, scenario_id: scenarioParam || undefined });
      const next = new URLSearchParams(params);
      next.delete("run");
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantRun, s?.id]);

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "signal") next.delete("scenario");
    next.delete("run");
    setParams(next, { replace: true });
  };

  const result: StressResult | undefined = stress.data;
  const partial = s?.status === "PARTIAL";

  return (
    <>
      <PageHeader
        title="Portfolio Stress"
        sub="Pick an event, apply its mapped scenario, and see what the shock does to a synthetic wholesale-banking book. The arithmetic is deterministic and shown."
      />

      {/* Controls */}
      <Card className="mb-5" title="Scenario run">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block">
            <span className="eyebrow mb-1.5 block">Event</span>
            <select className="field" value={signalId} onChange={(e) => set("signal", e.target.value || null)}>
              <option value="">Select an event…</option>
              {[...(signals.data?.items ?? [])]
                .sort((a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1))
                .map((x) => (
                  <option key={x.id} value={x.id}>
                    {x.impact_score ?? "–"} · {x.entity_name ?? "Unresolved entity"}: {x.headline.slice(0, 70)}
                  </option>
                ))}
            </select>
          </label>
          <label className="block">
            <span className="eyebrow mb-1.5 block">Scenario template</span>
            <select className="field" value={scenarioId} disabled={!s} onChange={(e) => set("scenario", e.target.value === defaultScenarioId ? null : e.target.value)}>
              {!s && <option value="">Select an event first</option>}
              {scenarios.data?.scenarios.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                  {x.id === defaultScenarioId ? " (mapped to this event)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>

        {s && (
          <div className="mt-5 flex flex-wrap items-start justify-between gap-x-8 gap-y-4 border-t border-rule pt-5">
            <div className="min-w-0 basis-80 flex-1">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <CategoryTag category={s.event.category} label={label(s.event.category)} />
                {s.entity.entity_id !== "UNKNOWN_ENTITY" ? (
                  <span className="text-sm text-ink-2">{s.entity.entity_name}</span>
                ) : (
                  <span className="text-sm text-warn">Entity unresolved</span>
                )}
              </div>
              <Link to={`/events/${s.id}`} className="font-medium leading-snug underline-offset-2 hover:text-accent-strong hover:underline">
                {s.document.headline}
              </Link>
            </div>
            <div className="flex flex-col gap-3">
              <ImpactMeter
                score={s.impact?.score ?? null}
                showLabel
                showKind={!!s.impact && s.data_origin !== "DEMO_FIXTURE"}
                kind={s.impact && s.data_origin !== "DEMO_FIXTURE" ? impactKind(s) : undefined}
                range={s.impact?.score_low != null && s.impact.score_high != null ? [s.impact.score_low, s.impact.score_high] : null}
              />
              {!partial && (
                <label className="flex items-center gap-2 text-sm text-ink-2">
                  <input type="checkbox" className="accent-[var(--color-accent)]" checked={whatIf} onChange={(e) => setWhatIf(e.target.checked)} />
                  What-if: override impact
                </label>
              )}
              {whatIf && (
                <label className="flex items-center gap-3 text-sm">
                  <input type="range" min={1} max={10} step={0.5} value={impact} onChange={(e) => setImpact(Number(e.target.value))} aria-label="What-if impact score" className="w-40" />
                  <span className="num w-10 text-ink">{impact.toFixed(1)}</span>
                </label>
              )}
            </div>
            <button className="btn btn-primary self-end" data-loading={stress.isPending} disabled={stress.isPending || partial} onClick={() => run()}>
              {stress.isPending ? <Spinner size={14} /> : <Play size={13} />}
              {stress.isPending ? "Running" : result ? "Run again" : "Run stress test"}
            </button>
          </div>
        )}
        {signal.isLoading && signalId && <Loading label="Loading event" />}
        {signal.error && (
          <div className="mt-4"><ErrorState error={signal.error} /></div>
        )}
        {partial && s && (
          <div className="mt-4">
            <InlineNote tone="warn" title="This signal has no impact score">
              {s.status_reason} It cannot be mapped to a scenario. Pick another event.
            </InlineNote>
          </div>
        )}
      </Card>

      {/* States */}
      {stress.error && <ErrorState error={stress.error} retry={() => run()} />}

      {!signalId && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <Card title="Start from a triggering event" aside={`Impact ≥ ${threshold}`}>
            {signals.isLoading ? (
              <Loading />
            ) : (
              <ul className="divide-y divide-rule">
                {(signals.data?.items ?? [])
                  .filter((x) => (x.impact_score ?? 0) >= threshold)
                  .sort((a, b) => (b.impact_score ?? 0) - (a.impact_score ?? 0))
                  .map((x) => (
                    <li key={x.id}>
                      <button
                        className="group flex w-full items-start gap-4 py-3 text-left transition-colors hover:bg-paper-3"
                        onClick={() => setParams({ signal: x.id, run: "1" }, { replace: true })}
                      >
                        <span className="pl-2"><ImpactMeter score={x.impact_score} kind={x.data_origin === "DEMO_FIXTURE" ? undefined : summaryKind(x)} showKind={x.data_origin !== "DEMO_FIXTURE"} /></span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium leading-snug group-hover:text-accent-strong">{x.headline}</span>
                          <span className="mt-0.5 block text-xs text-muted">{x.entity_name ?? "Market-wide, no single issuer"} · {label(x.category)}</span>
                        </span>
                        <ArrowRight size={14} className="mt-1 mr-2 shrink-0 text-muted" />
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </Card>
          <PortfolioGlance />
        </div>
      )}

      {signalId && !stress.isPending && !partial && s && (!result || result.status !== "COMPLETED") && (
        <div className="grid gap-5">
          <ShocksTable shocks={[]} scenario={selectedScenario} />
          <PortfolioGlance />
        </div>
      )}

      {result && result.status !== "COMPLETED" && (
        <Notice
          tone={result.status === "NOT_TRIGGERED" ? "info" : "warn"}
          title={
            result.status === "NOT_TRIGGERED"
              ? "Not triggered"
              : result.status === "NO_SCENARIO"
                ? "No scenario mapped"
                : "Stress test unavailable"
          }
          action={
            result.status === "NOT_TRIGGERED" ? (
              <button className="btn" onClick={() => run({ force: true })}>Run as what-if anyway</button>
            ) : undefined
          }
        >
          {result.reason}
        </Notice>
      )}

      {result?.status === "COMPLETED" && (
        <div className="grid gap-5">
          <ResultHero r={result} />
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <Breakdown r={result} entityNames={entityNames} />
            <TopPositions r={result} />
          </div>
          <ShocksTable shocks={result.shocks} scenario={selectedScenario} />
          {result.uncovered && result.uncovered.asset_count > 0 && (
            <Notice tone="warn" title={`${result.uncovered.asset_count} positions received no shock (${pct(result.uncovered.share_of_portfolio, 1)} of value)`}>
              They are not treated as safe; they are simply outside this scenario&apos;s reach. Pick a broader scenario to include them.
            </Notice>
          )}
          <PositionsTable positions={result.positions} />
          <AuditPanel r={result} />
        </div>
      )}

      {signalId && !s && !signal.isLoading && !signal.error && <EmptyState title="Event not found" />}
      <div className={clsx(stress.isPending && "sr-only")} aria-live="polite">
        {stress.isPending && "Running stress test"}
      </div>
    </>
  );
}

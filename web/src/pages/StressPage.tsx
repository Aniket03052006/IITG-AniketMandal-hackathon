import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMeta, usePortfolioExposure, usePortfolioSummary, useScenarios, useSignal, useSignals, useStressTest } from "../api/hooks";
import type { ExposureRow, StressResult } from "../api/types";
import { FlowRail } from "../components/FlowRail";
import { useOpenDrawer } from "../components/Drawer";
import { ArrowRight, Play, Spinner, Wrench } from "../components/icons";
import { ContributionDrill } from "../components/portfolio/ContributionDrill";
import { ResultHero } from "../components/portfolio/ResultHero";
import { StressDrawers } from "../components/portfolio/StressDrawers";
import { Waterfall } from "../components/portfolio/Waterfall";
import { WhatIf } from "../components/portfolio/WhatIf";
import { Sigma, Inputs as ListIcon } from "../components/icons";
import { StateNotice } from "../components/StateNotice";
import { EmptyState, ErrorState, ImpactMeter, Loading, Skeleton, Stat, StatusTag } from "../components/ui";
import { ASSET_CLASS_LABEL, money, pct } from "../lib/format";
import { impactKind, summaryKind } from "../lib/impact";
import { categoryLabeler } from "../lib/taxonomy";
import { KindBadge } from "../components/ProvenanceKind";

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
    <section className="glance" aria-label="The portfolio being stressed">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">The portfolio being stressed</h2>
        <StatusTag tone="demo">Synthetic</StatusTag>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <Stat label="Total value" value={s ? money(s.total_value) : "–"} sub={s?.base_currency} />
        <Stat label="Positions" value={s?.asset_count ?? "–"} sub="Equities, bonds, loans, derivatives" />
        <Stat label="Issuers" value={s?.entity_count ?? "–"} />
      </div>
      {s && <p className="mt-3 max-w-[70ch] text-xs text-muted">{s.description}</p>}
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
    </section>
  );
}

/** The payoff screen: the event's consequence for a portfolio, drawn to scale, drillable, and testable at another severity. */
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
  const main = useStressTest(); // at the event's own impact
  const sim = useStressTest(); // what-if severity
  const [, setOpen] = useOpenDrawer();

  const s = signal.data;
  const eventImpact = s?.impact?.score ?? null;
  const [severity, setSeverity] = useState<number>(7);
  const autoRan = useRef("");
  const threshold = meta?.trigger_threshold ?? 7;
  const defaultScenarioId = s ? scenarios.data?.default_by_category[s.event.category] : undefined;
  const scenarioId = scenarioParam || defaultScenarioId || "";
  const selectedScenario = scenarios.data?.scenarios.find((x) => x.id === scenarioId);
  const entityNames = useMemo(() => new Map((exposure.data?.by_entity ?? []).map((r) => [r.key, r.label])), [exposure.data]);
  const partial = s?.status === "PARTIAL";

  useEffect(() => {
    main.reset();
    sim.reset();
    if (eventImpact != null) setSeverity(eventImpact);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signalId, s?.id]);

  const run = (force = false) => {
    if (!signalId) return;
    main.mutate({ signal_id: signalId, scenario_id: scenarioParam || undefined, force });
  };

  useEffect(() => {
    if (wantRun && s && autoRan.current !== s.id) {
      autoRan.current = s.id;
      main.mutate({ signal_id: s.id, scenario_id: scenarioParam || undefined });
      const next = new URLSearchParams(params);
      next.delete("run");
      setParams(next, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantRun, s?.id]);

  // a different severity: recompute with the real engine, debounced so dragging does not flood it
  const base: StressResult | undefined = main.data?.status === "COMPLETED" ? main.data : undefined;
  const differs = eventImpact != null && severity !== eventImpact;
  useEffect(() => {
    if (!base || !signalId || !differs) return;
    const t = setTimeout(() => sim.mutate({ signal_id: signalId, scenario_id: scenarioParam || undefined, force: true, impact_override: severity }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [severity, base?.run_id, differs]);

  const shown: StressResult | undefined = differs && sim.data?.status === "COMPLETED" ? sim.data : base;
  const result = main.data;

  const set = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "signal") next.delete("scenario");
    next.delete("run");
    setParams(next, { replace: true });
  };

  return (
    <>
      {s && (
        <FlowRail
          active="stress"
          eventId={s.id}
          context={
            <>
              <span className="font-medium text-ink">{s.entity.entity_name ?? "Company not identified"}</span>
              {s.event.status === "CLASSIFIED" ? ` · ${label(s.event.category)}` : ""}
              {s.impact ? ` · impact ${s.impact.score}/10` : ""}
            </>
          }
        />
      )}

      <header className="mb-6">
        <h1 className="text-2xl font-semibold">Portfolio Stress</h1>
        <p className="mt-1 max-w-[66ch] text-md text-ink-2">What the event's scenario does to a synthetic wholesale-banking book. The shocks are assumptions; the arithmetic is deterministic and shown.</p>
      </header>

      {/* The event and scenario in play */}
      <section className="mb-8" aria-label="Event and scenario">
        {s && (
          <div className="ctl">
            <div className="min-w-0">
              <p className="eyebrow">Event</p>
              <Link to={`/events/${s.id}`} className="mt-1 block font-display text-lg font-semibold leading-snug underline-offset-2 hover:text-accent hover:underline">
                {s.document.headline}
              </Link>
              <p className="mt-1 text-sm text-muted">
                {s.entity.entity_id !== "UNKNOWN_ENTITY" ? s.entity.entity_name : "Company not identified"} · scenario <span className="text-ink-2">{selectedScenario?.name ?? "none mapped"}</span>
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <ImpactMeter
                score={s.impact?.score ?? null}
                showLabel
                showKind={!!s.impact && s.data_origin !== "DEMO_FIXTURE"}
                kind={s.impact && s.data_origin !== "DEMO_FIXTURE" ? impactKind(s) : undefined}
                range={s.impact?.score_low != null && s.impact.score_high != null ? [s.impact.score_low, s.impact.score_high] : null}
              />
              <button className="btn btn-primary" data-loading={main.isPending} disabled={main.isPending || partial} onClick={() => run()}>
                {main.isPending ? <Spinner size={14} /> : <Play size={13} />}
                {main.isPending ? "Running" : result ? "Run again" : "Run scenario"}
              </button>
            </div>
          </div>
        )}
        <details className="disclosure mt-3" open={!signalId || undefined}>
          <summary>{signalId ? "Change event or scenario" : "Choose an event"}</summary>
          <div className="mt-3 grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="eyebrow mb-1.5 block">Event</span>
              <select className="field" value={signalId} onChange={(e) => set("signal", e.target.value || null)}>
                <option value="">Select an event…</option>
                {[...(signals.data?.items ?? [])]
                  .filter((x) => x.impact_score != null)
                  .sort((a, b) => (b.impact_score ?? -1) - (a.impact_score ?? -1) || a.id.localeCompare(b.id))
                  .slice(0, 150)
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
        </details>
        {signal.isLoading && signalId && <Loading label="Loading event" />}
        {signal.error && <div className="mt-4"><ErrorState error={signal.error} /></div>}
        {partial && s && (
          <div className="mt-4 max-w-[68ch]">
            <StateNotice
              tone="warn"
              what="This signal has no impact score"
              why={`${s.status_reason} It cannot be mapped to a scenario, and EventShock will not substitute a default.`}
              next={<button className="btn" onClick={() => set("signal", null)}>Pick another event</button>}
            />
          </div>
        )}
      </section>

      {main.error && <ErrorState error={main.error} retry={() => run()} />}

      {!signalId && (
        <div className="grid gap-10">
          <section aria-label="Triggering events">
            <h2 className="mb-1 text-lg font-semibold">Start from a triggering event</h2>
            <p className="mb-3 text-sm text-muted">Events at impact ≥ {threshold} trigger a scenario.</p>
            {signals.isLoading ? (
              <Loading />
            ) : (
              <ul className="divide-y divide-rule border-y border-rule">
                {(signals.data?.items ?? [])
                  .filter((x) => (x.impact_score ?? 0) >= threshold)
                  .sort((a, b) => (b.impact_score ?? 0) - (a.impact_score ?? 0) || a.id.localeCompare(b.id))
                  .map((x) => (
                    <li key={x.id}>
                      <button className="group flex w-full items-start gap-4 py-3 text-left transition-colors hover:bg-paper-3" onClick={() => setParams({ signal: x.id, run: "1" }, { replace: true })}>
                        <span className="pl-2">
                          <ImpactMeter score={x.impact_score} kind={x.data_origin === "DEMO_FIXTURE" ? undefined : summaryKind(x)} showKind={x.data_origin !== "DEMO_FIXTURE"} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block font-medium leading-snug group-hover:text-accent-strong">{x.headline}</span>
                          <span className="mt-0.5 block text-xs text-muted">
                            {x.entity_name ?? "Market-wide, no single issuer"} · {label(x.category)}
                          </span>
                        </span>
                        <ArrowRight size={14} className="mt-1 mr-2 shrink-0 text-muted" />
                      </button>
                    </li>
                  ))}
              </ul>
            )}
          </section>
          <PortfolioGlance />
        </div>
      )}

      {signalId && s && !partial && !main.isPending && !result && (
        <div className="grid gap-10">
          <StateNotice tone="info" what="Ready to run" why="Use Run scenario above to see the portfolio before and after." />
          <PortfolioGlance />
        </div>
      )}

      {main.isPending && !result && <Skeleton className="h-64 w-full" />}

      {result && result.status !== "COMPLETED" && (
        <div className="max-w-[72ch]">
          <StateNotice
            tone={result.status === "NOT_TRIGGERED" ? "info" : "warn"}
            what={result.status === "NOT_TRIGGERED" ? "Below the trigger threshold" : result.status === "NO_SCENARIO" ? "No scenario mapped to this event type" : "Stress test unavailable"}
            why={result.reason}
            next={
              result.status === "NOT_TRIGGERED" ? (
                <button className="btn" onClick={() => run(true)}>
                  Run as what-if anyway
                </button>
              ) : undefined
            }
          />
        </div>
      )}

      {shown && result?.status === "COMPLETED" && (
        <div className="grid gap-12">
          <ResultHero r={shown} s={s} onShowAssumptions={() => setOpen("assumptions")} />

          {s?.entity.entity_id === "UNKNOWN_ENTITY" && (
            <div className="max-w-[68ch]">
              <StateNotice tone="warn" what="Only market-wide shocks applied" why="No company was linked to this event, so issuer- and sector-specific shocks had nothing to attach to." />
            </div>
          )}

          <div className="grid gap-12 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <section aria-label="Change by asset class">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-lg font-semibold">The change, step by step</h3>
                <KindBadge kind="scenario" />
              </div>
              <Waterfall rows={shown.contributions?.by_asset_class ?? []} total={shown.summary?.pnl ?? 0} />
            </section>
            <ContributionDrill r={shown} entityNames={entityNames} />
          </div>

          {eventImpact != null && (
            <WhatIf
              eventImpact={eventImpact}
              severity={severity}
              onSeverity={setSeverity}
              base={base}
              scenario={sim.data?.status === "COMPLETED" ? sim.data : undefined}
              pending={sim.isPending}
              onShowMath={() => setOpen("math")}
            />
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-5" role="group" aria-label="Explanations">
            <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setOpen("math")}>
              <Sigma size={14} /> How calculated?
            </button>
            <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setOpen("assumptions")}>
              <Wrench size={14} /> Assumptions
            </button>
            <button type="button" className="btn" aria-haspopup="dialog" onClick={() => setOpen("positions")}>
              <ListIcon size={14} /> Show every position
            </button>
            <button type="button" className="btn btn-ghost" aria-haspopup="dialog" onClick={() => setOpen("audit")}>
              Audit trail
            </button>
          </div>
        </div>
      )}

      {signalId && !s && !signal.isLoading && !signal.error && <EmptyState title="Event not found" />}
      <StressDrawers r={shown} scenario={selectedScenario} />
      <div className="sr-only" aria-live="polite">
        {(main.isPending || sim.isPending) && "Running stress test"}
      </div>
    </>
  );
}

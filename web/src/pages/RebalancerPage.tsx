import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMeta, useRebalancerBacktest, useRebalancerCycle, useRebalancerDecisions, useRebalancerLab, useRebalancerLedger, useRebalancerOverview, useRebalancerTimeline } from "../api/hooks";
import type { RebalancerQuery } from "../api/client";
import { BacktestCard } from "../components/rebalancer/BacktestCard";
import { CyclePicker } from "../components/rebalancer/CyclePicker";
import { DecisionBoard } from "../components/rebalancer/DecisionBoard";
import { DriversPanel } from "../components/rebalancer/DriversPanel";
import { LedgerTable } from "../components/rebalancer/LedgerTable";
import { RuleCard } from "../components/rebalancer/RuleCard";
import { StrategyLab } from "../components/rebalancer/StrategyLab";
import { StrategyPicker } from "../components/rebalancer/StrategyPicker";
import { TiltTiles } from "../components/rebalancer/TiltTiles";
import { TradesPanel } from "../components/rebalancer/TradesPanel";
import { WeightsChart, type ChartView } from "../components/rebalancer/WeightsChart";
import { WeightsTable } from "../components/rebalancer/WeightsTable";
import { WhatIf, type WhatIfValues } from "../components/rebalancer/WhatIf";
import { StateNotice } from "../components/StateNotice";
import { Tabs, useTab } from "../components/Tabs";
import { Card, ErrorState, PageHeader, Skeleton, Stat } from "../components/ui";
import { SECTOR_ORDER, orderSeries, pp, share, sectorVar } from "../lib/rebalancer";

const when = (iso: string) => `${new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" })} UTC`;

const TABS = [
  { id: "index", label: "The index" },
  { id: "decisions", label: "Trade decisions" },
  { id: "lab", label: "Strategy lab" },
  { id: "ledger", label: "Ledger" },
] as const;
const TAB_IDS = TABS.map((t) => t.id);
const BASELINE = "sentiment";

/**
 * Module A: a mock index whose weights follow the engine's sentiment. Four views of one story: how the weights moved and why (the index), what to trade this cycle and on whose
 * headlines (trade decisions, with a simulated approval), how the rule compares with the alternatives (strategy lab) and what was decided (ledger). The parameters in the URL
 * are a what-if for this view only.
 */
export function RebalancerPage() {
  const { data: meta } = useMeta();
  const on = meta?.capabilities.rebalancer === true;
  const [sp, setSp] = useSearchParams();
  const num = (k: string): number | null => {
    const v = sp.get(k);
    const n = v == null || v === "" ? NaN : Number(v);
    return Number.isFinite(n) ? n : null;
  };
  const strategy = sp.get("strategy") || BASELINE;
  const q: RebalancerQuery = { tilt: num("tilt"), half_life_hours: num("hl"), max_turnover: num("to"), include_live: sp.get("live") === "1", strategy: strategy === BASELINE ? null : strategy };
  const [tab, setTab] = useTab(TAB_IDS, "index");
  const overview = useRebalancerOverview(on);
  const timeline = useRebalancerTimeline(q, on);
  const backtest = useRebalancerBacktest(on && tab === "index");
  const tl = timeline.data;
  const last = (tl?.cycles.length ?? 1) - 1;
  const cycle = Math.min(Math.max(num("cycle") ?? last, 0), Math.max(last, 0));
  const hasCycles = !!tl && tl.cycles.length > 0;
  const detail = useRebalancerCycle(hasCycles ? cycle : null, q, on && hasCycles && tab === "index");
  const proposal = useRebalancerDecisions(hasCycles ? cycle : null, q, on && hasCycles && tab === "decisions");
  const lab = useRebalancerLab(on && tab === "lab");
  const ledger = useRebalancerLedger(on && tab === "ledger");
  const [view, setView] = useState<ChartView>("stack");
  const [hover, setHover] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const series = useMemo(() => (tl ? orderSeries(tl.constituents, tl.tickers) : []), [tl]);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) (v == null ? next.delete(k) : next.set(k, v));
    setSp(next, { replace: true });
  };
  const onWhatIf = (v: Partial<WhatIfValues>) =>
    set({ ...(v.tilt !== undefined ? { tilt: String(v.tilt) } : {}), ...(v.half_life_hours !== undefined ? { hl: String(v.half_life_hours) } : {}), ...(v.max_turnover !== undefined ? { to: String(v.max_turnover) } : {}) });

  if (meta && !on) return <StateNotice what="The rebalancer is not available here." why="The tactical index rebalancer runs in the replay profile." />;

  const names = detail.data?.names ?? [];
  const biggest = [...names].sort((a, b) => Math.abs(b.active) - Math.abs(a.active))[0]?.ticker ?? null;
  const selected = picked && names.some((n) => n.ticker === picked) ? picked : biggest;
  const focus = hover ?? picked; // what the chart and tiles emphasise: only what the reader points at or picked, never an automatic choice
  const over = [...names].sort((a, b) => b.active - a.active)[0];
  const under = [...names].sort((a, b) => a.active - b.active)[0];
  const params = tl?.params ?? overview.data?.params;
  const live = meta?.capabilities.live_enabled === true;

  return (
    <>
      <PageHeader
        title="Tactical index rebalancer"
        sub="A mock 15-stock index whose weights follow the sentiment score of the NLP risk engine: positive news raises a stock's weight, negative news lowers it, within bounds and a turnover limit."
        actions={live ? (
          <button type="button" className="chip" aria-pressed={q.include_live === true} onClick={() => set({ live: q.include_live ? null : "1" })}>Include the live feed</button>
        ) : undefined}
      />

      {timeline.isLoading && <div className="space-y-3"><Skeleton className="h-24 w-full" /><Skeleton className="h-96 w-full" /></div>}
      {timeline.error && <ErrorState error={timeline.error} retry={() => timeline.refetch()} />}
      {overview.data && !overview.data.available && (
        <StateNotice tone="info" what="There is nothing to rebalance yet." why="No report about a stock in the index has been published, so the index holds its equal-weight benchmark. Nothing is invented to fill the gap." />
      )}

      {tl && tl.cycles.length > 0 && params && (
        <div className="space-y-6">
          {!params.is_default && (
            <StateNotice tone="warn" what="You are looking at a what-if." why={<>Tilt <span className="num">{params.tilt}</span>, half-life <span className="num">{params.half_life_hours} h</span>, turnover cap <span className="num">{share(params.max_turnover)}</span> per cycle differ from the shipped parameters. The index of record is unchanged.</>}
              next={<button type="button" className="btn btn-sm" onClick={() => set({ tilt: null, hl: null, to: null })}>Back to the shipped parameters</button>} />
          )}

          {overview.data && overview.data.strategies.length > 1 && (
            <StrategyPicker strategies={overview.data.strategies} value={strategy} onChange={(id) => set({ strategy: id === BASELINE ? null : id })} />
          )}
          <Tabs tabs={[...TABS]} active={tab} onChange={setTab} label="Rebalancer views">
            {tab === "index" && (
              <div className="space-y-6">
            <section aria-label="Summary" className="card card-pad grid grid-cols-2 gap-x-6 gap-y-4 lg:grid-cols-5">
              <Stat label="Index" value={`${tl.tickers.length} stocks`} sub="equal-weight benchmark" />
              <Stat label="Cycles" value={tl.cycles.length} sub={`every ${overview.data?.step_hours ?? 6} h, ${when(tl.cycles[0]!.at)} to ${when(tl.cycles[last]!.at)}`} />
              <Stat label="Average turnover" value={share(tl.mean_turnover)} sub={`per cycle · ${share(tl.cumulative_turnover, 0)} in total`} />
              <Stat label="Reports used" value={tl.reports_used} sub={tl.excluded_untrusted_clock > 0 ? `${tl.excluded_untrusted_clock} social posts left off: their time was assigned by the replay` : "news and social"} />
              <Stat label="Most over, most under" value={over && under ? <span className="block text-base leading-snug"><span className="block">{over.ticker} <span className="text-pos">{pp(over.active, 1)}</span></span><span className="block">{under.ticker} <span className="text-neg">{pp(under.active, 1)}</span></span></span> : "–"} sub="at the selected cycle" />
            </section>

            <Card title="Weights over time" aside={<span className="num">{tl.cycles.length} cycles</span>}>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div role="group" aria-label="Chart view" className="flex items-center gap-2">
                  <button type="button" className="chip" aria-pressed={view === "stack"} onClick={() => setView("stack")}>Weights</button>
                  <button type="button" className="chip" aria-pressed={view === "active"} onClick={() => setView("active")}>Active vs benchmark</button>
                </div>
                <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-ink-2" aria-label="Sectors">
                  {SECTOR_ORDER.filter((s) => series.some((x) => x.sector === s)).map((s) => (
                    <li key={s} className="inline-flex items-center gap-1.5"><i className="rb-swatch" style={{ background: `var(${sectorVar(s)})` }} aria-hidden="true" />{s}</li>
                  ))}
                </ul>
              </div>
              <WeightsChart timeline={tl} series={series} view={view} cycle={cycle} onCycle={(i) => set({ cycle: String(i) })} focus={focus} onFocus={setHover} />
              <div className="mt-3"><CyclePicker times={tl.cycles.map((c) => c.at)} cycle={cycle} onChange={(i) => set({ cycle: i == null ? null : String(i) })} /></div>
              <p className="mt-2 text-xs text-muted">Click the chart or drag the slider to choose a cycle; arrow keys move it when the chart has focus. The table, trades and reasons below follow the selected cycle.</p>
            </Card>

            {detail.data && (
              <>
                <Card title={`The index at ${when(detail.data.at)}`} aside="exact figures behind the chart">
                  <WeightsTable detail={detail.data} series={series} focus={focus} onHover={setHover} onSelect={(t) => setPicked(picked === t ? null : t)} />
                </Card>
                <div className="grid gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
                  <Card title="What was traded"><TradesPanel detail={detail.data} /></Card>
                  <Card title={selected ? `Why ${selected} holds this weight` : "Why a stock holds its weight"}>
                    {selected ? <DriversPanel detail={detail.data} ticker={selected} name={series.find((s) => s.ticker === selected)?.name ?? selected} /> : <p className="text-sm text-muted">Pick a stock in the table.</p>}
                  </Card>
                </div>
              </>
            )}

            <Card title="Each stock against its benchmark" aside="same vertical scale in every tile">
              <TiltTiles timeline={tl} series={series} cycle={cycle} focus={focus} onHover={setHover} onSelect={(t) => setPicked(picked === t ? null : t)} />
            </Card>

            {overview.data && (
              <Card title="How the rule works" aside="every number is a judgement prior">
                <RuleCard overview={overview.data} params={params} />
                <details className="mt-5 rounded-md border border-rule p-3">
                  <summary className="cursor-pointer text-sm font-medium">What-if controls</summary>
                  <div className="mt-4"><WhatIf overview={overview.data} params={params} onChange={onWhatIf} onReset={() => set({ tilt: null, hl: null, to: null })} /></div>
                </details>
              </Card>
            )}

            <Card title="Back-test" aside="an illustration, not evidence of skill">
              {backtest.isLoading && <Skeleton className="h-32 w-full" />}
              {backtest.error && <ErrorState error={backtest.error} retry={() => backtest.refetch()} />}
              {backtest.data && <BacktestCard view={backtest.data} />}
            </Card>

            <section aria-label="Labels and limits" className="space-y-1 text-xs text-muted">
              <ul className="list-disc space-y-1 pl-5">{[...tl.labels, ...tl.limitations].map((l) => <li key={l}>{l}</li>)}</ul>
            </section>
              </div>
            )}
            {tab === "decisions" && (
          <div className="space-y-6">
            <Card title="The rebalance at this cycle" aside={proposal.data ? <span className="num">{proposal.data.strategy}</span> : undefined}>
              <CyclePicker times={tl.cycles.map((c) => c.at)} cycle={cycle} onChange={(i) => set({ cycle: i == null ? null : String(i) })} id="rb-cycle-d" />
              {overview.data && (
                <details className="mt-4 rounded-md border border-rule p-3">
                  <summary className="cursor-pointer text-sm font-medium">Adjust the limits for this proposal (a what-if)</summary>
                  <div className="mt-4"><WhatIf overview={overview.data} params={params} onChange={onWhatIf} onReset={() => set({ tilt: null, hl: null, to: null })} /></div>
                </details>
              )}
            </Card>
            {proposal.isLoading && <Skeleton className="h-64 w-full" />}
            {proposal.error && <ErrorState error={proposal.error} retry={() => proposal.refetch()} />}
            {proposal.data && <DecisionBoard proposal={proposal.data} series={series} q={q} />}
          </div>
            )}
            {tab === "lab" && (
          <div>
            {lab.isLoading && <Skeleton className="h-64 w-full" />}
            {lab.error && <ErrorState error={lab.error} retry={() => lab.refetch()} />}
            {lab.data && <StrategyLab view={lab.data} />}
          </div>
            )}
            {tab === "ledger" && (
          <div>
            {ledger.isLoading && <Skeleton className="h-40 w-full" />}
            {ledger.error && <ErrorState error={ledger.error} retry={() => ledger.refetch()} />}
            {ledger.data && <LedgerTable view={ledger.data} />}
          </div>
            )}
          </Tabs>
        </div>
      )}
    </>
  );
}

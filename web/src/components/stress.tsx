import clsx from "clsx";
import { Fragment, useMemo, useState } from "react";
import type { AppliedShock, Contribution, PositionResult, Scenario, StressResult } from "../api/types";
import { ASSET_CLASS_LABEL, FACTOR_LABEL, SCOPE_LABEL, money, moneyFull, pct, shockValue } from "../lib/format";
import { lifecycleKind } from "../lib/impact";
import { originLabel } from "../lib/provenance";
import { ImpactLifecycleTag } from "./ImpactLifecycleTag";
import { Chevron } from "./icons";
import { Card, StatusTag } from "./ui";

/* ----------------------------------------------------------------------------- hero */

export function ResultHero({ r }: { r: StressResult }) {
  const s = r.summary;
  if (!s || !r.scenario || !r.severity) return null;
  return (
    <section className="card card-pad" aria-label="Portfolio value before and after stress">
      <div className="flex flex-wrap items-center gap-2">
        <StatusTag tone="ok">Computed · deterministic engine</StatusTag>
        <StatusTag tone="warn">Illustrative scenario assumptions</StatusTag>
        {r.audit.forced && <StatusTag tone="demo">What-if run</StatusTag>}
        {r.audit.impact_origin && !r.audit.impact_overridden && (
          <ImpactLifecycleTag kind={r.audit.impact_origin === "MODEL" ? lifecycleKind(r.audit.impact_lifecycle) : "placeholder"} detail="impact that triggered this" />
        )}
      </div>
      <div className="mt-5 grid gap-x-10 gap-y-6 md:grid-cols-[repeat(3,minmax(0,auto))] md:justify-start">
        <div className="min-w-0">
          <p className="eyebrow">Before stress</p>
          <p className="num mt-1 font-display text-4xl font-medium">{money(s.baseline_value)}</p>
          <p className="num text-xs text-muted">{moneyFull(s.baseline_value)}</p>
        </div>
        <div className="min-w-0">
          <p className="eyebrow">After stress</p>
          <p className="num mt-1 font-display text-4xl font-medium">{money(s.stressed_value)}</p>
          <p className="num text-xs text-muted">{moneyFull(s.stressed_value)}</p>
        </div>
        <div className="min-w-0">
          <p className="eyebrow">Change</p>
          <p className={clsx("num mt-1 font-display text-4xl font-medium", s.pnl < 0 ? "text-neg" : "text-pos")}>
            {money(s.pnl, { signed: true })}
          </p>
          <p className={clsx("num text-sm", s.pnl < 0 ? "text-neg" : "text-pos")}>{pct(s.pnl_pct, 2, true)} of portfolio value</p>
        </div>
      </div>
      <p className="mt-5 border-t border-rule pt-4 text-sm text-muted">
        <span className="text-ink-2">{r.scenario.name}</span> v{r.scenario.version}. Severity scaling:{" "}
        <span className="num text-ink-2">{r.severity.formula}</span>
      </p>
    </section>
  );
}

/* --------------------------------------------------------------------------- shocks */

export function ShocksTable({ shocks, scenario }: { shocks: AppliedShock[]; scenario?: Scenario }) {
  const scaled = shocks.length > 0;
  const rows = scaled
    ? shocks.map((s) => ({ factor: s.factor, scope: s.scope, base: s.base_value, applied: s.scaled_value as number | null, applicable: s.applicable, why: s.rationale }))
    : (scenario?.shocks ?? []).map((s) => ({ factor: s.factor, scope: s.scope, base: s.value, applied: null as number | null, applicable: true, why: s.rationale }));
  if (rows.length === 0) return null;
  return (
    <Card title="Shock assumptions" aside={scaled ? "Scaled to this event's impact" : "At reference impact"} pad={false}>
      <div className="scroll-x">
        <table className="dtable min-w-[40rem]">
          <thead>
            <tr>
              <th>Risk factor</th>
              <th>Applies to</th>
              <th className="text-right">At reference</th>
              {scaled && <th className="text-right">Applied</th>}
              <th>Rationale</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.factor}-${r.scope}`} className={clsx(!r.applicable && "opacity-50")}>
                <td className="font-medium">{FACTOR_LABEL[r.factor] ?? r.factor}</td>
                <td className="text-ink-2">
                  {SCOPE_LABEL[r.scope] ?? r.scope}
                  {!r.applicable && <span className="ml-1 text-xs text-warn">(no entity resolved)</span>}
                </td>
                <td className="num text-right text-muted">{shockValue(r.factor, r.base)}</td>
                {scaled && <td className="num text-right font-medium">{r.applied === null ? "–" : shockValue(r.factor, r.applied)}</td>}
                <td className="text-muted">{r.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-rule px-4 py-2.5 text-xs text-muted">
        Most specific scope wins per factor (issuer, then sector, then market-wide), so nothing is double counted. Magnitudes are illustrative, not forecasts.
      </p>
    </Card>
  );
}

/* ----------------------------------------------------------------------- breakdowns */

type Tab = "asset" | "sector" | "entity" | "factor";

function LossBar({ baseline, delta, maxBase }: { baseline: number; delta: number; maxBase: number }) {
  const lossFrac = baseline > 0 ? Math.min(1, Math.max(0, -delta) / baseline) : 0;
  const w = maxBase > 0 ? (baseline / maxBase) * 100 : 0;
  return (
    <span className="block h-2.5" aria-hidden="true">
      <span className="flex h-full overflow-hidden rounded-sm bg-paper-4" style={{ width: `${Math.max(w, 2)}%` }}>
        <span className="h-full bg-faint" style={{ width: `${(1 - lossFrac) * 100}%` }} />
        {lossFrac > 0 && <span className="h-full min-w-[2px] bg-neg" style={{ width: `${lossFrac * 100}%` }} />}
      </span>
    </span>
  );
}

export function Breakdown({ r, entityNames }: { r: StressResult; entityNames: Map<string, string> }) {
  const [tab, setTab] = useState<Tab>("asset");
  const c = r.contributions;
  if (!c) return null;
  const sets: Record<Tab, { label: string; rows: Contribution[] }> = {
    asset: { label: "Asset class", rows: c.by_asset_class },
    sector: { label: "Sector", rows: c.by_sector },
    entity: { label: "Issuer", rows: c.by_entity },
    factor: { label: "Risk factor", rows: c.by_factor },
  };
  const rows = sets[tab].rows;
  const maxBase = Math.max(0, ...rows.map((x) => x.baseline_value));
  const maxAbs = Math.max(1, ...rows.map((x) => Math.abs(x.delta)));
  const name = (x: Contribution) =>
    tab === "asset" ? (ASSET_CLASS_LABEL[x.key] ?? x.key) : tab === "entity" ? (entityNames.get(x.key) ?? x.key) : tab === "factor" ? (FACTOR_LABEL[x.key] ?? x.key) : x.label;

  return (
    <Card
      title="Where the change comes from"
      aside={
        <div role="group" aria-label="Group by" className="flex flex-wrap justify-end gap-1">
          {(Object.keys(sets) as Tab[]).map((t) => (
            <button key={t} className="chip" aria-pressed={tab === t} onClick={() => setTab(t)}>
              {sets[t].label}
            </button>
          ))}
        </div>
      }
    >
      <div className="scroll-x">
        <table className="dtable min-w-[36rem]">
          <thead>
            <tr>
              <th>{sets[tab].label}</th>
              {tab !== "factor" && <th className="text-right">Before</th>}
              <th className="text-right">Change</th>
              {tab !== "factor" && <th className="text-right">Δ %</th>}
              <th className="text-right" title="Positions that gain offset the total, so shares can exceed 100%">Share of change</th>
              <th className="w-[28%]">{tab === "factor" ? "Contribution" : "Before → after"}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((x) => (
              <tr key={x.key}>
                <td className="font-medium">{name(x)}</td>
                {tab !== "factor" && <td className="num text-right text-muted">{money(x.baseline_value)}</td>}
                <td className={clsx("num text-right", x.delta < 0 ? "text-neg" : x.delta > 0 ? "text-pos" : "text-muted")}>
                  {money(x.delta, { signed: true })}
                </td>
                {tab !== "factor" && (
                  <td className="num text-right text-muted">{x.baseline_value > 0 ? pct(x.delta / x.baseline_value, 2, true) : "–"}</td>
                )}
                <td className="num text-right">{x.share_of_loss === null ? "–" : pct(x.share_of_loss, 0)}</td>
                <td className="pt-3">
                  {tab === "factor" ? (
                    <span className="block h-2.5 rounded-sm bg-paper-4" aria-hidden="true">
                      <span className={clsx("block h-full rounded-sm", x.delta < 0 ? "bg-neg" : "bg-pos")} style={{ width: `${(Math.abs(x.delta) / maxAbs) * 100}%` }} />
                    </span>
                  ) : (
                    <LossBar baseline={x.baseline_value} delta={x.delta} maxBase={maxBase} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tab !== "factor" && (
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
          <span className="flex items-center gap-1.5"><i className="inline-block h-2 w-3 rounded-[1px] bg-faint" /> value after stress</span>
          <span className="flex items-center gap-1.5"><i className="inline-block h-2 w-3 rounded-[1px] bg-neg" /> value lost</span>
          <span>Bar length is proportional to value before stress.</span>
        </p>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------------- top positions */

export function TopPositions({ r }: { r: StressResult }) {
  const top = r.contributions?.top_positions ?? [];
  const max = Math.max(1, ...top.map((t) => Math.abs(t.delta)));
  if (top.length === 0) return null;
  return (
    <Card title="Largest loss contributors" aside={`Top ${top.length} positions`}>
      <ol className="space-y-2.5">
        {top.map((t, i) => (
          <li key={t.key} className="grid grid-cols-[1.25rem_minmax(0,1fr)_5.25rem] items-center gap-3 text-sm">
            <span className="num text-xs text-muted">{i + 1}</span>
            <span className="min-w-0">
              <span className="block truncate text-ink-2" title={t.label}>{t.label}</span>
              <span className="mt-1 block h-1.5 rounded-sm bg-paper-4" aria-hidden="true">
                <span className={clsx("block h-full rounded-sm", t.delta < 0 ? "bg-neg" : "bg-pos")} style={{ width: `${(Math.abs(t.delta) / max) * 100}%` }} />
              </span>
            </span>
            <span className={clsx("num text-right", t.delta < 0 ? "text-neg" : "text-pos")}>{money(t.delta, { signed: true })}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

/* ------------------------------------------------------------------ positions table */

export function PositionsTable({ positions }: { positions: PositionResult[] }) {
  const [cls, setCls] = useState<string>("");
  const [open, setOpen] = useState<string | null>(null);
  const classes = useMemo(() => [...new Set(positions.map((p) => p.asset_class))], [positions]);
  const rows = cls ? positions.filter((p) => p.asset_class === cls) : positions;
  return (
    <Card title="Every position" aside={`${rows.length} of ${positions.length}`} pad={false}>
      <div className="flex flex-wrap gap-1.5 px-4 pb-3" role="group" aria-label="Filter positions by asset class">
        <button className="chip" aria-pressed={cls === ""} onClick={() => setCls("")}>All</button>
        {classes.map((c) => (
          <button key={c} className="chip" aria-pressed={cls === c} onClick={() => setCls(cls === c ? "" : c)}>
            {ASSET_CLASS_LABEL[c] ?? c}
          </button>
        ))}
      </div>
      <div className="scroll-x max-h-[34rem] overflow-y-auto">
        <table className="dtable min-w-[44rem]">
          <thead className="sticky top-0 bg-paper-2">
            <tr>
              <th className="w-8" />
              <th>Position</th>
              <th>Class</th>
              <th className="text-right">Before</th>
              <th className="text-right">After</th>
              <th className="text-right">Change</th>
              <th className="text-right">Δ %</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => {
              const isOpen = open === p.asset_id;
              return (
                <Fragment key={p.asset_id}>
                  <tr className="cursor-pointer hover:bg-paper-3" onClick={() => setOpen(isOpen ? null : p.asset_id)}>
                    <td>
                      <button
                        className="btn-ghost -m-1 rounded-sm p-1"
                        aria-expanded={isOpen}
                        aria-label={`Show calculation for ${p.name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setOpen(isOpen ? null : p.asset_id);
                        }}
                      >
                        <Chevron size={13} className={clsx("transition-transform", isOpen && "rotate-90")} />
                      </button>
                    </td>
                    <td className="max-w-[22rem] truncate font-medium" title={p.name}>{p.name}</td>
                    <td className="text-muted">{ASSET_CLASS_LABEL[p.asset_class] ?? p.asset_class}</td>
                    <td className="num text-right text-muted">{money(p.baseline_value)}</td>
                    <td className="num text-right">{money(p.stressed_value)}</td>
                    <td className={clsx("num text-right", p.delta < 0 ? "text-neg" : p.delta > 0 ? "text-pos" : "text-muted")}>{money(p.delta, { signed: true })}</td>
                    <td className="num text-right text-muted">{pct(p.delta_pct, 1, true)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="bg-paper">
                      <td />
                      <td colSpan={6} className="pb-3">
                        <p className="num text-xs break-words text-ink-2">{p.formula}</p>
                        {p.shocks.length === 0 ? (
                          <p className="mt-1 text-xs text-warn">No shock applied to this position under this scenario.</p>
                        ) : (
                          <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-muted">
                            {p.shocks.map((s) => (
                              <span key={s.factor}>
                                {FACTOR_LABEL[s.factor]} <span className="num text-ink-2">{shockValue(s.factor, s.value)}</span> ({SCOPE_LABEL[s.scope]?.toLowerCase()})
                              </span>
                            ))}
                          </p>
                        )}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------------------ audit */

export function AuditPanel({ r }: { r: StressResult }) {
  const a = r.audit;
  const rows: [string, string][] = [
    ["Run id", r.run_id],
    ["Mode", a.mode === "REPLAY" ? "Replay (deterministic)" : "Live"],
    ["Signal data", originLabel(a.data_origin)],
    ["Scenario", r.scenario ? `${r.scenario.id} v${a.scenario_version}` : "–"],
    ["Engine", `v${a.engine_version}`],
    ["Portfolio", `${a.portfolio_id} #${a.portfolio_hash}`],
    ["Impact used", a.impact_overridden ? "what-if override" : a.impact_origin === "MODEL" ? `trained model · ${(a.impact_lifecycle ?? "").toLowerCase()}` : a.impact_origin === "PLACEHOLDER" ? "placeholder rule" : "–"],
    ["Trigger threshold", `impact ≥ ${a.threshold}${a.forced ? " (overridden: what-if)" : ""}`],
    ["Calculated at", new Date(a.calculated_at).toISOString().replace(".000Z", "Z")],
  ];
  return (
    <Card title="Audit" aside="Same inputs, same result">
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1.5 text-xs sm:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted">{k}</dt>
            <dd className="num break-all">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-muted">{a.calculation}. Run id is a hash of signal, scenario version, impact, and portfolio holdings.</p>
    </Card>
  );
}
